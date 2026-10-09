# reading csv
def read_csv(path, sep=";") -> dict:
    # read a CSV file and store the result in a dictionary
    # → 𝑝𝑎𝑡ℎ: path (relative or not) of the CSV file
    # → 𝑠𝑒𝑝: separator used in the CSV file
    # the format of the output dictionary can be described like this :
    #   if we see the CSV file as a matrix Aᵢⱼ (where A₀ⱼ is the first line)
    #   then 𝑑𝑖𝑐𝑜[Aᵢ₀][A₀ⱼ] = Aᵢⱼ
    dico = {}
    with open(path,'r',encoding="utf-8") as file:
        lines = file.read().split('\n')
    keys = lines[0].split(sep)
    for line in lines[1:]:
        if len(line)>0:
            item = {}
            split = line.split(sep)
            if len(split)>1:
                for i in range(len(split)):
                    item[keys[i]] = split[i]
            dico[split[0]] = item
    return dico

# technical constants
diacritics = {"a":"àâä","c":"ç","e":"éèêï","i":"îï","o":"ôö","u":"ûü"}
letters = "abcdefghijklmnopqrstuvwxyz"
ernestien = {"a":"n","â":"n̂","b":"Ր","c":"","d":"Þ","e":"c","ê":"ĉ","f":"ɸ","g":"ᕋ","h":"ʃ","i":"ı","î":"î","j":"J","k":"¢","l":"ʟ̥","m":"ᒐ","n":"ᒉ","o":"o","ô":"ô","p":"г̊","q":"🐠","r":"Ꞁ̊","s":"c̥","t":"⟊","u":"u","û":"û","v":"v̥","z":"∤"," ":"  "}

# functions
def transcription_ernestien(text:str) -> str:
    # use the 𝑒𝑟𝑛𝑒𝑠𝑡𝑖𝑒𝑛 to write with ernestian alphabet from a 𝑡𝑒𝑥𝑡 written with the latin alphabet
    # warning, if the 𝑡𝑒𝑥𝑡 have other chars than aâbcdeêfghiîjklmnoôpqrstuûvz, an error is returned
    return "".join([ernestien[c] for c in text])

def normalize_text(text:str):
    # lower uppercases, remove diactrics and pop other special chars
    result = ""
    for c in text.lower():
        if c in letters:
            result += c
        else:
            for a in diacritics:
                if c in diacritics[a]:
                    result += a
    return result
