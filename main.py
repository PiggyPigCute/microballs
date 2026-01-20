import discord
from discord.ext import commands
import random
import time
import re

# constants
PROBA = 0.1  # probability of sending a ball when a msg is sent
WAIT_DURATION = 5  # time (in seconds) after a msg is sent, during this time the msg are ignored
EMOJI_GUILD_ID = 1462239696418635840  # id of the guild where the the emojis are stored (here, the MicroBall guild)

# reading-write csv
def read_csv(path,sep=";"):
    dico = {}
    with open(path,'r',encoding="utf-8") as file:
        lines = file.read().split('\n')
    keys = lines[0].split(sep)
    for line in lines[1:]:
        item = {}
        split = line.split(sep)
        if len(split)>1:
            for i in range(len(split)):
                item[keys[i]] = split[i]
        dico[split[0]] = item
    return dico

def write_csv(path,dico:dict,keys,sep=";"):
    text = sep.join(keys)
    for mini_dico in dico.values():
        text += '\n'
        for key in keys:
            if key in mini_dico:
                text += mini_dico[key]
            text += sep
        text = text[:-1]
    with open(path,'w',encoding="utf-8") as file:
        file.write(text)

# variables
balls = read_csv(r"./balls.csv")
balls_id = list(balls.keys())
players_keys = ["player_id"]+balls_id
spawn_channels = read_csv(r"./channels.csv")
players = read_csv(r"./players.csv")
emojis = {} # set on on_ready()

# technical constants
mini_digits = {'1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉'}
diacritics = {"a":"àâä","c":"ç","e":"éèêï","i":"îï","o":"ôö","u":"ûü"}
letters = "abcdefghijklmnopqrstuvwxyz"
ernestien = {"a":"n","â":"n̂","b":"Ր","d":"Þ","e":"c","ê":"ĉ","f":"ɸ","g":"ᕋ","h":"ʃ","i":"ı","ê":"î","j":"J","k":"¢","l":"ʟ̥","m":"ᒐ","n":"ᒉ","o":"o","ô":"ô","p":"г̊","r":"Ꞁ̊","s":"c̥","t":"⟊","u":"u","û":"û","v":"v̥","z":"∤"}

# time
current_time = time.time()
last_triggers = {int(guild_id):current_time for guild_id in spawn_channels}

# bot initialization
class CustomHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        ...
    async def send_command_help(self, command):
        ...

bot = commands.Bot(command_prefix="/", intents=discord.Intents.default(), help_command=CustomHelpCommand())


# functions
def normalize_text(text):
    result = ""
    for c in text.lower():
        if c in letters:
            result += c
        else:
            for a in diacritics:
                if c in diacritics[a]:
                    result += a
    return result

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
        if self.caught_view.caught:
            await inter.response.send_message("Désolé **"+inter.user.display_name+"**, la MicroBall a déjà été attrapée par **"+self.caught_view.catcher_name+"**")
            return

        awnser = normalize_text(inter.data["components"][0]["components"][0]["value"])
        ball = balls[self.ball_id]
        if re.match(ball["regex_fr"], awnser) != None:
            await inter.response.send_message("Bravo <@"+str(inter.user.id)+">, tu as capturé **"+ball["nom_fr"]+"** !")
            await self.caught_view.catch(inter.user)
        elif re.match(ball["regex_ens"], awnser) != None:
            await inter.response.send_message("Bravo <@"+str(inter.user.id)+">, tu as capturé **"+"".join([ernestien[c] for c in ball["nom_ens"]])+"** !\n-# (Ces caractères étranges sont de l'ernestien, la langue de l'Ernestie. "+inter.user.display_name+" vient d'attraper la MicroBall en écrivant le nom en ernestien)")
            await self.caught_view.catch(inter.user)
        else:
            await inter.response.send_message("Désolé **"+inter.user.display_name+"**, ce n'est pas le bon nom")

class CatchView(discord.ui.View):
    def __init__(self, ball_id):
        super().__init__(timeout=None)
        self.ball_id = ball_id
        self.caught = False
        self.catcher_name = None
        self.msg = None

    @discord.ui.button(label="Attraper !", style=discord.ButtonStyle.primary, custom_id="catch")
    async def open_modal(self, inter:discord.Interaction, button: discord.ui.Button):
        await inter.response.send_modal(BoxModal(self.ball_id,self))
    
    async def catch(self, catcher:discord.Member):
        self.caught = True
        self.catcher_name = catcher.display_name
        self.disabled = True
        await self.msg.edit(view=None)
        catcher_id, ball_id = str(catcher.id), str(self.ball_id)
        if catcher_id in players:
            player = players[catcher_id]
            if ball_id in player and player[ball_id] != "":
                player[ball_id] = str(1+int(player[ball_id]))
            else:
                player[ball_id] = "1"
        else:
            players[catcher_id] = {"player_id":catcher_id}
            for ball in balls_id:
                players[catcher_id][ball] = ""
            players[catcher_id][ball_id] = "1"
        write_csv(r"./players.csv",players,players_keys)
        print(" 🪵 🤚  catch │ player:",catcher.display_name,"│ ball:",ball_id,"│ guild:",self.msg.guild.name)
        
    def set_msg(self,msg:discord.Message):
        self.msg = msg

@bot.event
async def on_ready():
    await bot.tree.sync()
    for emoji in bot.get_guild(EMOJI_GUILD_ID).emojis:
        emojis[emoji.name] = "<:"+emoji.name+":"+str(emoji.id)+"> "
    print("Let's go !")

@bot.event
async def on_message(message:discord.Message):
    if message.author.bot: return

    int_guild_id = message.guild.id
    str_guild_id = str(int_guild_id)

    if not str_guild_id in spawn_channels:
        print(" 🪵 📜  unregistered channel │ guild:", message.guild.name, "│ guild_id:", message.guild.id)
        return

    current_time = time.time()
    if current_time-last_triggers[int_guild_id]<WAIT_DURATION: return
    last_triggers[int_guild_id] = current_time

    try:
        channel = message.guild.get_channel(int(spawn_channels[str_guild_id]["channel_id"]))
    except:
        print(" 🪵 🤔 erreur get_channel │ guild:",message.guild.name,"│ channel_id:",spawn_channels[str_guild_id]["channel_id"])
        return

    rand = random.random()
    print(" 🪵 🌿  trigger │ guild:", message.guild.name, "│ rand:",rand)
    if rand < PROBA:
        ball_id = random.choice(balls_id)
        with open("./img/"+balls[ball_id]["img"]+".png", "rb") as file:
            picture = discord.File(file)
        print(" 🪵 🏀  microball │ ball:", ball_id, "│ guild:", message.guild.name)
        view = CatchView(ball_id)
        msg = await channel.send("Une MicroBall vient d'apparaître !\n** **", file=picture, view=view)
        view.set_msg(msg)

@bot.tree.command(name="set-channel", description="Exécuter cette commande dans le salon où vous voulez que les MicroBalls apparaissent")
async def set_channel(inter:discord.Interaction):
    await inter.response.defer(ephemeral=True)
    if inter.user.guild_permissions.manage_channels:
        guild_id = str(inter.guild.id)
        channel_id = str(inter.channel.id)
        if guild_id in spawn_channels:
            spawn_channels[guild_id]["channel_id"] = channel_id
        else:
            spawn_channels[guild_id] = {"guild_id":guild_id,"channel_id":channel_id}
            last_triggers[inter.guild.id] = time.time()
        write_csv("./channels.csv",spawn_channels,("guild_id","channel_id","special"))
        await inter.followup.send("Dans le serveur **"+inter.guild.name+"**, les MicroBalls vont apparaître dans le salon **<#"+str(inter.channel.id)+">**", ephemeral=True)
        print(" 🪵 🔧 set-channel │ guild:",inter.guild.name,"│ channel:",inter.channel.name,"│ user:",inter.user.name)
    else:
        await inter.followup.send("⚠️ Il vous faut la permission **`manage-channels`** pour exécuter cette commande :)", ephemeral=True)
        print(" 🪵 🤐 set-channel no permission │ guild:",inter.guild.name,"│ user:",inter.user.name)

@bot.tree.command(name="info", description="Obtenir des informations sur le bot MicroBalls")
async def info(inter:discord.Interaction):
    await inter.response.defer(ephemeral=True)
    guild_id = str(inter.guild.id)
    if guild_id in spawn_channels:
        text = "Dans le serveur *"+inter.guild.name+"*, c'est le salon <#"+spawn_channels[guild_id]["channel_id"]+"> qui a été choisi pour faire apparaître les MicroBalls. Pour changer le salon d'apparission, vous pouvez utiliser la commande `/set-channel` dans le salon voulu"
    else:
        text = "Pour l'instant dans le serveur *"+inter.guild.name+"*, aucun salon n'a été sélectionné pour faire apparaître les MicroBalls. Utilisez la commande `/set-channel` dans le salon voulu pour les faire apparaître !"
    await inter.followup.send(embed=discord.embeds.Embed(color=discord.Color.blue(),title="MicroBalls",description="Salut, je suis le bot **MicroBalls**, créé par **PiggyPig** (`@piggypig`).\n\nLe principe est simple, lorsque le serveur est actif des *MicroBalls* (CountryBalls de micronations) apparaissent. Les membres du serveurs ont alors 5 minutes pour essayer d'attraper la MicroBall en cliquant sur le bouton et en inscrivant le nom de la micronation (en français ou en ernestien).\n\nVous pouvez faire `/collection` pour obtenir votre collection et voir quelle MicroBalls il vous manque. Vous pouvez aussi faire `/give` pour donner une MicroBall à quelqu'un d'autre.\n\n"+text+" (vous devez avoir la permission *manage_channels*)."),ephemeral=True)

@bot.tree.command(name="collection", description="Regarde la liste des MicroBalls que tu as")
async def collection(inter:discord.Interaction):
    await inter.response.defer()
    player_id = str(inter.user.id)
    if player_id in players:
        player = players[player_id]
        caught_balls, uncaught_balls = [], []
        for ball_id in balls:
            if ball_id in player and player[ball_id] != "":
                caught_balls.append((int(player[ball_id]),emojis[ball_id]+("ₓ"+"".join([mini_digits[c] for c in player[ball_id]]) if player[ball_id] != "1" else "")))
            else:
                uncaught_balls.append(emojis[ball_id])
        caught_balls.sort(key=lambda x: -int(x[0]))
        text = "MicroBalls attrapées :\n# " + " ".join([x[1] for x in caught_balls]) + "\n\nMicroBalls à attraper :\n### "+" ".join(uncaught_balls)
    else:
        text = "Tu n'as attrapé aucune MicroBall pour l'instant, voici la liste des MicroBalls existantes :\n### " + " ".join([emojis[ball] for ball in balls])
    await inter.followup.send(embed=discord.embeds.Embed(color=discord.Color.blue(),title="Collection de **"+inter.user.display_name+"**",description=text))

# go !
with open(r"./token.lock", 'r') as file:
    token = file.read()
bot.run(token)