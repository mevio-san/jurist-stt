import json

config = json.load(open("config.json", "r"))
flavor = config.get("flavor", "sandbox")