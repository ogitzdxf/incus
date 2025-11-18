import discord
from discord import app_commands
from discord.ext import commands
import asyncio, shlex, json, os, math
from datetime import datetime
from discord.ui import Button, View, Modal, TextInput

# ---------------------------
# CONFIG: Set your token & main admin
# ---------------------------
TOKEN = "PUT-YOUR-BOT-TOKEN-HERE"
MAIN_ADMIN = 1295737579840340032  # change to your id

# ---------------------------
# BOT SETUP
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------
# Simple JSON helpers
# ---------------------------
def _ensure_dir():
    if not os.path.isdir("."):
        os.makedirs(".", exist_ok=True)

def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# Data files
user_data = load_json("user_data.json", {})   # { user_id: {"credits": int} }
vps_data = load_json("vps_data.json", {})     # { user_id: [ {container, ram, cpu, os, ports, status, created_at} ] }
admin_data = load_json("admin_data.json", {"admins": []})

# ---------------------------
# Settings / images / pricing
# ---------------------------
CREDITS_PER_2GB = 10  # every 2GB costs this many credits

IMAGES = {
    "ubuntu": "images:ubuntu/22.04",
    "ubuntu20": "images:ubuntu/20.04",
    "ubuntu24": "images:ubuntu/24.04",
    "debian": "images:debian/12",
    "debian11": "images:debian/11",
    "almalinux": "images:almalinux/9",
    "rockylinux": "images:rockylinux/9",
    "centos": "images:centos/7",
    "kali": "images:kali/current",
    "arch": "images:archlinux/current"
}

# ---------------------------
# Incus command wrapper
# ---------------------------
async def icmd(cmd, timeout=300):
    proc = await asyncio.create_subprocess_exec(
        *shlex.split(cmd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise Exception("Command timed out")
    out_s = out.decode().strip()
    err_s = err.decode().strip()
    if proc.returncode != 0:
        raise Exception(err_s or out_s or f"Command failed: {cmd}")
    return out_s

# ---------------------------
# Embed & watermark helpers
# ---------------------------
def make_embed(title, desc, color=0x2f3136):
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text=f"CurlNode VPS Manager • {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\nCreated by ogitzdude ||rawrage.dxf||")
    return e

def wm_text(msg):
    return f"{msg}\n\nCreated by ogitzdude ||rawrage.dxf||"

# ---------------------------
# Helpers
# ---------------------------
def credits_required_for_ram(ram_gb: int) -> int:
    blocks = math.ceil(ram_gb / 2)
    return blocks * CREDITS_PER_2GB

def ensure_user_data(uid: str):
    if uid not in user_data:
        user_data[uid] = {"credits": 0}

def ensure_vps_list(uid: str):
    if uid not in vps_data:
        vps_data[uid] = []

def save_all():
    save_json("user_data.json", user_data)
    save_json("vps_data.json", vps_data)
    save_json("admin_data.json", admin_data)

# ---------------------------
# Startup
# ---------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"[{datetime.utcnow().isoformat()}] Bot ready. Slash commands synced.")

# ---------------------------
# HELP command
# ---------------------------
@bot.tree.command(name="help", description="Show help and commands")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="📚 CurlNode VPS Manager — Help", color=0x0dd3a8)
    e.description = "Use slash commands below. Contact admin for issues."
    e.add_field(name="🚀 VPS Commands", value=(
        "`/myvps` — View your VPS list\n"
        "`/buy <ram_gb> <cpu> <os>` — Create VPS using credits\n"
        "`/create_admin @user <ram_gb> <cpu> <os>` — Admin create for user\n    "
    ), inline=False)
    e.add_field(name="🔧 Control", value=(
        "`/start <index>` — Start your VPS\n"
        "`/stop <index>` — Stop your VPS\n"
        "`/restart <index>` — Restart your VPS\n"
        "`/delete <index>` — Delete your VPS\n"
    ), inline=False)
    e.add_field(name="🔌 Network & Terminal", value=(
        "`/port <index> <port>` — Forward host IPv4 port to VPS\n"
        "`/terminal <index>` — Open tmate web/ssh terminal\n"
    ), inline=False)
    e.add_field(name="💰 Credits", value=(
        "`/credits` — View your credits\n"
        "`/addcredit @user <amount>` — Admin: add credits\n\n"
        f"Pricing rule: **Every 2GB RAM = {CREDITS_PER_2GB} credits** (CPU does not cost credits)"
    ), inline=False)
    e.add_field(name="🛠 Additional", value=(
        "`/manage` — Interactive VPS manager\n"
        "`/rename <index> <new_name>` — Rename your VPS\n"
        "`/usage <index>` — Check RAM/CPU usage\n"
        "`/transfer <index> @new_owner` — Transfer VPS to another user\n"
        "`/extend <index> <new_ram> <new_cpu>` — Upgrade using credits\n        "
    ), inline=False)
    e.set_footer(text="Made for Incus containers • IPv4 NAT & port forwarding supported\nCreated by ogitzdude ||rawrage.dxf||")
    await interaction.response.send_message(embed=e, ephemeral=True)

# ---------------------------
# Credits & Admin
# ---------------------------
@bot.tree.command(name="credits", description="Show your credit balance")
async def credits_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user_data(uid)
    bal = user_data[uid].get("credits", 0)
    await interaction.response.send_message(embed=make_embed("💰 Your Credits", f"You have **{bal}** credits."), ephemeral=True)

@bot.tree.command(name="addcredit", description="Admin: add credits to a user")
async def addcredit_cmd(interaction: discord.Interaction, user: discord.Member, amount: int):
    if interaction.user.id != MAIN_ADMIN and str(interaction.user.id) not in admin_data.get("admins", []):
        return await interaction.response.send_message(wm_text("❌ You do not have permission."), ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message(wm_text("❌ Amount must be positive."), ephemeral=True)
    uid = str(user.id)
    ensure_user_data(uid)
    user_data[uid]["credits"] += amount
    save_all()
    await interaction.response.send_message(embed=make_embed("✅ Credits Added", f"Added **{amount}** credits to {user.mention}.\nNew balance: **{user_data[uid]['credits']}**"))

# ---------------------------
# myvps
# ---------------------------
@bot.tree.command(name="myvps", description="List your VPS instances")
async def myvps_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_vps_list(uid)
    lst = vps_data.get(uid, [])
    if not lst:
        return await interaction.response.send_message(embed=make_embed("You have no VPS", "Use `/buy` to create one."))
    lines = []
    for i, v in enumerate(lst, start=1):
        ports = ", ".join(map(str, v.get("ports", []))) if v.get("ports") else "none"
        lines.append(f"**{i}.** `{v['container']}` • {v['ram']}GB RAM • {v['cpu']} CPU • OS: {v.get('os','unknown')} • Status: {v.get('status','unknown')} • Ports: {ports}")
    await interaction.response.send_message(embed=make_embed(f"📦 Your VPS ({len(lst)})", "\n".join(lines[:20])))

# ---------------------------
# buy command
# ---------------------------
@bot.tree.command(name="buy", description="Create a VPS using credits (self)")
async def buy_cmd(interaction: discord.Interaction, ram_gb: int, cpu: int, os_name: str = "ubuntu"):
    uid = str(interaction.user.id)
    ensure_user_data(uid)
    ensure_vps_list(uid)

    os_key = os_name.lower()
    if os_key not in IMAGES:
        return await interaction.response.send_message(wm_text("❌ Invalid OS. See `/help` for supported OS names."), ephemeral=True)
    if ram_gb <= 0 or cpu <= 0:
        return await interaction.response.send_message(wm_text("❌ RAM and CPU must be positive numbers."), ephemeral=True)

    cost = credits_required_for_ram(ram_gb)
    balance = user_data[uid]["credits"]
    if balance < cost:
        return await interaction.response.send_message(embed=make_embed("❌ Insufficient Credits", f"You need **{cost}** credits but have **{balance}**."), ephemeral=True)

    index = len(vps_data[uid]) + 1
    cname = f"vps-{uid}-{index}"
    ram_mb = ram_gb * 1024
    await interaction.response.send_message(wm_text(f"⏳ Deploying your VPS `{cname}` (cost: {cost} credits). This may take a minute..."), ephemeral=True)

    try:
        await icmd(f"incus launch {IMAGES[os_key]} {cname} --config limits.cpu={cpu} --config limits.memory={ram_mb}MB --storage btrpool")
        vps_entry = {"container": cname, "ram": ram_gb, "cpu": cpu, "os": os_key, "ports": [], "status": "running", "created_at": datetime.utcnow().isoformat()}
        vps_data[uid].append(vps_entry)
        user_data[uid]["credits"] -= cost
        save_all()
        await interaction.followup.send(embed=make_embed("✅ VPS Created", f"Your VPS `{cname}` is deployed.\nCredits used: **{cost}**\nRemaining balance: **{user_data[uid]['credits']}**"))
    except Exception as e:
        await interaction.followup.send(wm_text(f"❌ Deployment failed: {e}"))

# ---------------------------
# create_admin (admin creates for user)
# ---------------------------
@bot.tree.command(name="create_admin", description="Admin: create VPS for a user (no credit check)")
async def create_admin_cmd(interaction: discord.Interaction, user: discord.Member, ram_gb: int, cpu: int, os_name: str = "ubuntu"):
    if interaction.user.id != MAIN_ADMIN and str(interaction.user.id) not in admin_data.get("admins", []):
        return await interaction.response.send_message(wm_text("❌ You do not have permission."), ephemeral=True)
    os_key = os_name.lower()
    if os_key not in IMAGES:
        return await interaction.response.send_message(wm_text("❌ Invalid OS."), ephemeral=True)
    uid = str(user.id)
    ensure_vps_list(uid)
    index = len(vps_data[uid]) + 1
    cname = f"vps-{uid}-{index}"
    ram_mb = ram_gb * 1024
    await interaction.response.send_message(wm_text(f"⏳ Deploying `{cname}` for {user.mention}..."), ephemeral=True)
    try:
        await icmd(f"incus launch {IMAGES[os_key]} {cname} --config limits.cpu={cpu} --config limits.memory={ram_mb}MB --storage btrpool")
        vps_entry = {"container": cname, "ram": ram_gb, "cpu": cpu, "os": os_key, "ports": [], "status": "running", "created_at": datetime.utcnow().isoformat()}
        vps_data[uid].append(vps_entry)
        save_all()
        await interaction.followup.send(embed=make_embed("✅ VPS Created", f"`{cname}` created for {user.mention}"))
    except Exception as e:
        await interaction.followup.send(wm_text(f"❌ Deployment failed: {e}"))

# ---------------------------
# Terminal (tmate)
# ---------------------------
@bot.tree.command(name="terminal", description="Get a temporary tmate web/ssh session for your VPS")
async def terminal_cmd(interaction: discord.Interaction, index: int):
    uid = str(interaction.user.id)
    ensure_vps_list(uid)
    try:
        v = vps_data[uid][index - 1]
    except Exception:
        return await interaction.response.send_message(wm_text("❌ Invalid VPS index."), ephemeral=True)
    cname = v["container"]
    await interaction.response.send_message(wm_text("⏳ Preparing terminal (this may take ~20s)..."), ephemeral=True)
    try:
        await icmd(f"incus exec {cname} -- apt update -y")
        await icmd(f"incus exec {cname} -- apt install -y tmate")
        await icmd(f"incus exec {cname} -- tmate -S /tmp/tmate.sock new-session -d")
        ssh = await icmd(f"incus exec {cname} -- tmate -S /tmp/tmate.sock display -p '#{{tmate_ssh}}'")
        web = await icmd(f"incus exec {cname} -- tmate -S /tmp/tmate.sock display -p '#{{tmate_web}}'")
        await interaction.followup.send(embed=make_embed("🔑 Terminal Ready", f"**SSH:**\n`{ssh}`\n\n**WEB:**\n{web}"))
    except Exception as e:
        await interaction.followup.send(wm_text(f"❌ Terminal setup failed: {e}"))

# ---------------------------
# Control commands (start/stop/restart/delete)
# ---------------------------
@bot.tree.command(name="start", description="Start your VPS")
async def start_cmd(interaction: discord.Interaction, index: int):
    uid = str(interaction.user.id)
    ensure_vps_list(uid)
    try:
        cname = vps_data[uid][index - 1]["container"]
        await icmd(f"incus start {cname}")
        vps_data[uid][index - 1]["status"] = "running"
        save_all()
        await interaction.response.send_message(wm_text(f"✅ VPS `{cname}` started."))
    except Exception as e:
        await interaction.response.send_message(wm_text(f"❌ Failed to start: {e}"))

@bot.tree.command(name="stop", description="Stop your VPS")
async def stop_cmd(interaction: discord.Interaction, index: int):
    uid = str(interaction.user.id)
    ensure_vps_list(uid)
    try:
        cname = vps_data[uid][index - 1]["container"]
        await icmd(f"incus stop {cname} --force")
        vps_data[uid][index - 1]["status"] = "stopped"
        save_all()
        await interaction.response.send_message(wm_text(f"🛑 VPS `{cname}` stopped."))
    except Exception as e:
        await interaction.response.send_message(wm_text(f"❌ Failed to stop: {e}"))

@bot.tree.command(name="restart", description="Restart your VPS")
async def restart_cmd(interaction: discord.Interaction, index: int):
    uid = str(interaction.user.id)
    ensure_vps_list(uid)
    try:
        cname = vps_data[uid][index - 1]["container"]
        await icmd(f"incus restart {cname}")
        vps_data[uid][index - 1]["status"] = "running"
        save_all()
        await interaction.response.send_message(wm_text(f"🔄 VPS `{cname}` restarted."))
    except Exception as e:
        await interaction.response.send_message(wm_text(f"❌ Failed to restart: {e}"))

@bot.tree.command(name="delete", description="Delete your VPS (destructive)")
async def delete_cmd(interaction: discord.Interaction, index: int):
    uid = str(interaction.user.id)
    ensure_vps_list(uid)
    try:
        cname = vps_data[uid][index - 1]["container"]
        await interaction.response.send_message(wm_text(f"⏳ Deleting `{cname}` — this is permanent..."), ephemeral=True)
        await icmd(f"incus delete {cname} --force")
        vps_data[uid].pop(index - 1)
        save_all()
        await interaction.followup.send(embed=make_embed("✅ Deleted", f"`{cname}` has been deleted."))
    except Exception as e:
        await interaction.followup.send(wm_text(f"❌ Delete failed: {e}"))

# ---------------------------
# Port Forward Modal
# ---------------------------
class PortModal(Modal):
    def __init__(self, user_id: str, vps_index: int):
        super().__init__(title="Add Port Forward")
        self.user_id = user_id
        self.vps_index = vps_index
        self.port_input = TextInput(label="Port", placeholder="Enter host port number", required=True)
        self.add_item(self.port_input)