import csv, json, os

src = os.path.join(os.path.dirname(__file__), "airlines.dat.txt")
out = os.path.join(os.path.dirname(__file__), "app", "static", "js", "airlines.json")

airlines = []
with open(src, encoding="utf-8") as f:
    for row in csv.reader(f):
        if len(row) < 8:
            continue
        name, iata, active = row[1].strip(), row[3].strip(), row[7].strip()
        if not iata or iata == "-" or iata == r"\N" or active != "Y":
            continue
        country = row[6].strip()
        airlines.append({"iata": iata, "name": name, "country": country})

airlines.sort(key=lambda x: x["name"])

with open(out, "w", encoding="utf-8") as f:
    json.dump(airlines, f, separators=(",", ":"))

print(f"Done — {len(airlines)} airlines saved to {out}")
