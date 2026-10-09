import re
import time
import random
import discord
import asyncio
import database as db

from texts import read_csv, transcription_ernestien, normalize_text
from discord.ext import commands

# broadcast
BROADCAST_ACTIVE = False
BROADCAST_CONTENT = "Sallut, depuis quelques jours, vous avez pu voir des balles attrapées par **None**, non ce n'est pas Ulysse d'Itaque c'était bien un bug qui, normalement, n'apparaitra plus :grin:"

# constants
PROBA = 0.04  # probability of sending a ball when a msg is sent
WAIT_DURATION = 10  # time (in seconds) after a msg is sent, during this time the msg are ignored
EMOJI_GUILD_ID = 1462239696418635840  # id of the guild where the the emojis are stored (here, the MicroBall guild)
LOGS_GUILD_ID = 1462239696418635840  # id of the guild where the logs are sent
LOGS_MAIN_CHANNEL_ID = 1463155147625467978  # id of the channel where the logs (other than "trigger") are sent
LOGS_TRIGGER_CHANNEL_ID = 1475267245461733467 # od of the channel where the "trigger" logs are sent
ERROR_PING_ROLE_ID = 1467532432872833156
BOT_ADD_LINK = "https://discord.com/oauth2/authorize?client_id=1462241870158630913&permissions=3072&integration_type=0&scope=bot"

#global lock
#lock = asyncio.Lock()

# variables
db.init_db()
balls = read_csv(r"./balls.csv")
balls_id = list(balls.keys())
spawn_channels = db.get_spawn_channels()  # {guild_id: channel_id}

# variables set during on_ready()
emojis = {}
log_channels = {}

# technical constants
mini_digits = "₀₁₂₃₄₅₆₇₈₉"

# time
current_time = time.time()
last_triggers = {guild_id:current_time for guild_id in spawn_channels}

# log errors
async def log_error(exception, type="", **kwargs):
    await log_channels["main"].send("# :boom: Erreur !\n```ansi\n[2;33m"+type+"\n[2;1;4;31m"+str(exception)+"\n[0m[2;36m"+"\n".join(["- "+key+" : "+repr(kwargs[key]) for key in kwargs])+"```\n-# <@&"+str(ERROR_PING_ROLE_ID)+">")

# bot initialization
class CustomHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        ...
    async def send_command_help(self, command):
        ...

bot = commands.Bot(command_prefix="/", intents=discord.Intents.default(), help_command=CustomHelpCommand())

class BoxModal(discord.ui.Modal):
    def __init__(self, ball_id, caught_view):
        super().__init__(title="Attraper la MicroBall !")

        self.awnser = discord.ui.TextInput(
            label="Nom de la Micronation",
            placeholder="nom de la micronation",
            default="",
            required=True,
            max_length=200
        )

        self.add_item(self.awnser)

        self.ball_id = ball_id
        self.caught_view = caught_view

    async def on_submit(self, inter:discord.Interaction):
        try:
            #lock.acquire()
            if self.caught_view.caught:
                await inter.response.send_message("Désolé **"+inter.user.display_name+"**, la MicroBall a déjà été attrapée par **"+str(self.caught_view.catcher_name)+"**")
                return
            raw_awnser = inter.data["components"][0]["components"][0]["value"]
            awnser = normalize_text(raw_awnser)
            ball = balls[self.ball_id]
            if re.match(ball["regex_fr"], awnser) != None:
                self.caught_view.caught = True
                await inter.response.send_message("Bravo <@"+str(inter.user.id)+">, tu as capturé **"+ball["nom_fr"]+"** !")
                await self.caught_view.catch(inter.user, raw_awnser, language="fr")
                # await log_channels["main"].send(" 🪵 🤚  catch │ player: "+inter.user.name)
                # await log_channels["main"].send(" 🪵 🤚  catch │ ball: "+str(self.ball_id))
                # await log_channels["main"].send(" 🪵 🤚  catch │ guild: "+self.caught_view.msg.guild.name)
                # await log_channels["main"].send(" 🪵 🤚  catch │ awnser: "+raw_awnser)
            elif "regex_ens" in ball and re.match(ball["regex_ens"], awnser) != None:
                self.caught_view.caught = True
                await inter.response.send_message("Bravo <@"+str(inter.user.id)+">, tu as capturé **"+transcription_ernestien(ball["nom_ens"])+"** !\n-# (Ces caractères étranges sont de l'ernestien, la langue de l'Ernestie. "+inter.user.display_name+" vient d'attraper la MicroBall en écrivant le nom en ernestien)")
                await self.caught_view.catch(inter.user, raw_awnser, language="ens")
                # await log_channels["main"].send(" 🪵 🤚 🐠 ernest catch │ player: "+inter.user.name+" │ ball: "+str(self.ball_id)+" │ guild: "+self.caught_view.msg.guild.name, "│ awnser: "+raw_awnser)
            else:
                await inter.response.send_message("Désolé **"+inter.user.display_name+"**, ce n'est pas le bon nom")
                #lock.release()
        except Exception as exception:
            await log_error(exception, "BoxModal on_submit", guild=(inter.guild.name,inter.guild_id), ball=self.ball_id, caught=self.caught_view.caught)

class CatchView(discord.ui.View):
    def __init__(self, ball_id):
        super().__init__(timeout=None)
        self.ball_id = ball_id
        self.caught = False
        self.catcher_name = None
        self.msg = None
        

    @discord.ui.button(label="Attraper !", style=discord.ButtonStyle.primary, custom_id="catch")
    async def open_modal(self, inter:discord.Interaction, button: discord.ui.Button):
        try:
            await inter.response.send_modal(BoxModal(self.ball_id,self))
        except Exception as excepction:
            await log_error(excepction, "CatchView open_modal", guild=(inter.guild.name,inter.guild_id), ball=self.ball_id)
    
    async def catch(self, catcher:discord.Member, awnser, language:str):
        try:
            self.catcher_name = catcher.display_name
            self.disabled = True
            await self.msg.edit(view=None)
            microball_id = db.catch_ball(self.ball_id, catcher.id, language)
            await log_channels["main"].send(" 🪵 🤚"+" 🐠"*(language=="ens")+"  catch │ player: "+catcher.name+" │ awnser: "+awnser+" │ ball: "+self.ball_id+" │ microball_id: "+str(microball_id))
        except Exception as exception:
            await log_error(exception, "CatchView catch", caught=self.caught, ball=self.ball_id, catcher_name=self.catcher_name)
        
    def set_msg(self,msg:discord.Message):
        self.msg = msg

@bot.event
async def on_ready():
    await bot.tree.sync()
    guilds_list = "\n┌─ Guilds where MicroBalls is ─┐\n│ " + "\n│ ".join([guild.name for guild in bot.guilds]) + " \n└──────────────────────────────┘"
    print(guilds_list)
    log_channels["main"] = bot.get_guild(LOGS_GUILD_ID).get_channel(LOGS_MAIN_CHANNEL_ID)
    log_channels["trigger"] = bot.get_guild(LOGS_GUILD_ID).get_channel(LOGS_TRIGGER_CHANNEL_ID)
    await log_channels["main"].send(" 🪵 🎊  Let's Go !")
    await log_channels["main"].send(guilds_list.replace("\n","\n-# "))
    for emoji in bot.get_guild(EMOJI_GUILD_ID).emojis:
        emojis[emoji.name] = "<:"+emoji.name+":"+str(emoji.id)+"> "
    if BROADCAST_ACTIVE:
        for guild_id in spawn_channels:
            await bot.get_guild(guild_id).get_channel(spawn_channels[guild_id]).send(BROADCAST_CONTENT)
    
    print("Let's go !")

@bot.event
async def on_message(message:discord.Message):
    try:
        if message.author.bot: return

        guild_id = message.guild.id

        if not guild_id in spawn_channels:
            await log_channels["main"].send(" 🪵 📜  unregistered channel │ guild: "+message.guild.name+" │ guild_id: "+str(guild_id))
            return

        current_time = time.time()
        if current_time-last_triggers[guild_id]<WAIT_DURATION: return
        last_triggers[guild_id] = current_time

        try:
            channel = message.guild.get_channel(spawn_channels[guild_id])
        except:
            await log_channels["main"].send(" 🪵 🤔 erreur get_channel │ guild: "+message.guild.name+" │ channel_id: "+str(spawn_channels[guild_id]))
            return

        rand = random.random()
        await log_channels["trigger"].send(" 🪵 🌿  trigger │ guild: "+message.guild.name+" │ rand: "+str(rand))
        if rand < PROBA:
            ball_id = random.choice(balls_id)
            await log_channels["main"].send(" 🪵 🏀  microball │ ball: "+ball_id+" │ guild: "+message.guild.name)
            with open("./img/"+balls[ball_id]["img"]+".png", "rb") as file:
                picture = discord.File(file)
            view = CatchView(ball_id)
            try:
                msg = await channel.send("Une MicroBall vient d'apparaître !\n** **", file=picture, view=view)
            except:
                await log_channels["main"].send(" 🪵 ⛔ **forbidden ball │ ball: "+ball_id+" │ guild: "+message.guild.name+"**")
            view.set_msg(msg)
    except Exception as exception:
        await log_error(exception, "@bot.event on_messages", guild=(message.guild.name,message.guild.id), author=(message.author.name,message.author.id), channel=(message.channel.name,message.channel.id))

@bot.tree.command(name="set-channel", description="Exécuter cette commande dans le salon où vous voulez que les MicroBalls apparaissent")
async def set_channel(inter:discord.Interaction):
    try:
        await inter.response.defer(ephemeral=True)
        app_without_bot = True
        for guild in bot.guilds:
            if guild.id == inter.guild_id:
                app_without_bot = False
        if app_without_bot:
            await log_channels["main"].send(" 🪵 👻 set-channel app_without_bot │ guild: "+inter.guild.name+" ("+str(inter.guild_id)+") │ user: "+inter.user.name)
            await inter.followup.send("👻 Je ne suis pas sur ce serveur, l'application a été installée mais pas le bot n'a pas été ajouté.\nTu peux utiliser ce lien pour ajouter le bot : "+BOT_ADD_LINK, ephemeral=True)
        if inter.user.guild_permissions.manage_channels or inter.user.guild_permissions.administrator or inter.guild.owner_id == inter.user.id:
            guild_id = inter.guild.id
            if not guild_id in spawn_channels:
                last_triggers[guild_id] = time.time()
            spawn_channels[guild_id] = inter.channel.id
            db.set_spawn_channel(guild_id, inter.channel.id)
            await inter.followup.send("Dans le serveur **"+inter.guild.name+"**, les MicroBalls vont apparaître dans le salon **<#"+str(inter.channel.id)+">**", ephemeral=True)
            await log_channels["main"].send(" 🪵 🔧 set-channel │ guild: "+inter.guild.name+" │ channel: "+inter.channel.name+" │ user: "+inter.user.name)
        else:
            await log_channels["main"].send(" 🪵 🤐 set-channel no permission │ guild: "+inter.guild.name+" │ user: "+inter.user.name)
            await inter.followup.send("⚠️ Il vous faut la permission **`manage-channels`** pour exécuter cette commande :)", ephemeral=True)
    except Exception as exception:
        await log_error(exception, "command /set-channel", guild=(inter.guild.name,inter.guild_id), user=(inter.user.name,inter.user.id))

@bot.tree.command(name="info", description="Obtenir des informations sur le bot MicroBalls")
async def info(inter:discord.Interaction):
    try:
        await inter.response.defer(ephemeral=True)
        guild_id = inter.guild.id
        if guild_id in spawn_channels:
            text = "Dans le serveur *"+inter.guild.name+"*, c'est le salon <#"+str(spawn_channels[guild_id])+"> qui a été choisi pour faire apparaître les MicroBalls. Pour changer le salon d'apparission, vous pouvez utiliser la commande `/set-channel` dans le salon voulu"
        else:
            text = "Pour l'instant dans le serveur *"+inter.guild.name+"*, aucun salon n'a été sélectionné pour faire apparaître les MicroBalls. Utilisez la commande `/set-channel` dans le salon voulu pour les faire apparaître !"
        await inter.followup.send(embed=discord.embeds.Embed(color=discord.Color.blue(),title="MicroBalls",description="Salut, je suis le bot **MicroBalls**, créé par **PiggyPig** (`@piggypig`).\n\nLe principe est simple, lorsque le serveur est actif des *MicroBalls* (CountryBalls de micronations) apparaissent. Les membres du serveurs ont alors 5 minutes pour essayer d'attraper la MicroBall en cliquant sur le bouton et en inscrivant le nom de la micronation (en français ou en ernestien).\n\nVous pouvez faire `/collection` pour obtenir votre collection et voir quelle MicroBalls il vous manque. Vous pouvez aussi faire `/give` pour donner une MicroBall à quelqu'un d'autre.\n\n"+text+" (vous devez avoir la permission *manage_channels*)."),ephemeral=True)
    except Exception as exception:
        await log_error(exception, "command /info", guild=(inter.guild.name,inter.guild_id), user=(inter.user.name,inter.user.id))

async def collec(inter, language=None, precision="", color=discord.Color.blue()):
    # → 𝑙𝑎𝑛𝑔𝑢𝑎𝑔𝑒: if given, only show the MicroBalls caught in this language
    await inter.response.defer()
    counts = db.count_balls(inter.user.id, language)
    if counts:
        caught_balls = []
        for ball_id in balls:
            if ball_id in counts:
                n = counts[ball_id]
                caught_balls.append((n,emojis[ball_id]+("ₓ"+"".join([mini_digits[int(c)] for c in str(n)]) if n != 1 else "")))
        caught_balls.sort(key=lambda x: -x[0])
        text1 = "MicroBalls attrapées "+precision+":\n# " + " ".join([x[1] for x in caught_balls])
    else:
        caught_balls = []
        text1 = "Tu n'as attrapé aucune MicroBall "+precision+"pour l'instant"
    if len(caught_balls) == len(balls):
        text2 = "Féliciation, tu as attrapées toutes les MicroBalls "+precision+"! :tada:"
    else:
        text2 = "Il te reste " + str(len(balls)-len(caught_balls)) + " MicroBalls à découvrir "+precision
    await inter.followup.send(embed=discord.embeds.Embed(color=color,title="Collection de **"+inter.user.display_name+"** "+precision,description=text1+"\n\n"+text2))

@bot.tree.command(name="collection", description="Regarde la liste des MicroBalls que tu as")
async def collection(inter:discord.Interaction):
    try:
        await collec(inter)
    except Exception as exception:
        await log_error(exception, "command /collection", guild=(inter.guild.name,inter.guild_id), user=(inter.user.name,inter.user.id))

@bot.tree.command(name="ernestien-collection", description="Regarde la liste des MicroBalls que tu as attrapé en ernestien")
async def ernestien_collection(inter:discord.Interaction):
    try:
        await collec(inter, "ens", "en ernestien ", discord.Color.yellow())
    except Exception as exception:
        await log_error(exception, "command /ernestien-collection", guild=(inter.guild.name,inter.guild_id), user=(inter.user.name,inter.user.id))

@bot.tree.command(name="cadeau", description="Offre une MicroBall à quelqu'un")
@discord.app_commands.choices(ball_id=[discord.app_commands.Choice(name=balls[ball_id]["nom_fr"], value=ball_id) for ball_id in balls_id[:20]])
@discord.app_commands.describe(ball_id="MicroBall que vous voulez offrir")
@discord.app_commands.describe(destinataire="Personne à qui vous voulez offrir cette MicroBall")
@discord.app_commands.choices(langue=[discord.app_commands.Choice(name="Français", value=0),
                                      discord.app_commands.Choice(name="Ernestien", value=1)])
@discord.app_commands.describe(langue="Voulez-vous donner la version ernestienne de la MicroBall")
async def cadeau(inter:discord.Interaction, ball_id:str, destinataire:discord.User, langue:int=0):
    try:
        await inter.response.defer()
        sender_id = inter.user.id
        language = "ens" if langue else "fr"

        # if the 𝑠𝑒𝑛𝑑𝑒𝑟 has no french version of 𝑏𝑎𝑙𝑙_𝑖𝑑 but an ernestian one, then the 𝑠𝑒𝑛𝑑𝑒𝑟 give the ernestian version
        owned = db.count_languages(sender_id, ball_id)
        if language == "fr" and not "fr" in owned and "ens" in owned:
            language = "ens"

        microball_id = db.transfer_ball(ball_id, language, sender_id, destinataire.id)
        if microball_id is not None:
            dest_id = str(destinataire.id)
            await inter.followup.send(embed=discord.embeds.Embed(color=discord.Color.blue(),title=":gift: Cadeau !",description="<@"+str(sender_id)+"> a offert **"+(transcription_ernestien(balls[ball_id]["nom_ens"]) if language == "ens" else balls[ball_id]["nom_fr"])+"** à <@"+dest_id+">"))
            await log_channels["main"].send(" 🪵 🎁 cadeau │ sender: "+inter.user.name+" │ ball_id: "+ball_id+" │ to: "+destinataire.name+" │ "+db.LANGUAGES[language]+" │ microball_id: "+str(microball_id))
        else:
            await inter.followup.send("Désolé, tu ne possèdes pas cette MicroBall", ephemeral=True)
            await log_channels["main"].send(" 🪵 🎁 ❌ cadeau impossible │ sender: "+inter.user.name+" │ ball_id: "+ball_id+" │ "+db.LANGUAGES[language])
    except Exception as exception:
        await log_error(exception, "command /cadeau", guild=(inter.guild.name,inter.guild_id), user=(inter.user.name,inter.user.id))

# go !
with open(r"./token.lock", 'r') as file:
    token = file.read()
bot.run(token)