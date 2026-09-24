try:
    import pyperclip
except:
    print("Require: pip install pyperclip")
    exit(0)
import json

if __name__ == "__main__":
    try:
        with open("../json/skill_ico.json", mode="rb") as f:
            skills = json.load(f)
    except Exception as e:
        print(e)
        print("A new skill_ico.json will be created, input 'y' to continue")
        if input().lower() != "y":
            exit(0)
        skills = {}
    modified = False
    print("How-to: Go to the subskill selection menu and use the bookmarklet skill_export.js to copy the skills, then press Return here. Type 'q' or 'quit' when you're done.")
    while True:
        s = input().lower()
        if s in {"q","quit"}:
            break
        try:
            data = json.loads(pyperclip.paste())
        except:
            continue
        count = 0
        if isinstance(data, dict):
            data = [d for d in data.values()]
        elif not isinstance(data, list):
            continue
        for i in range(0, len(data)):
            try:
                aid = str(data[i]["action_id"])
                pid = str(data[i].get("perfection_ability_id", None))
                cn = data[i]["class_name"]
                ea = skills.get(aid, None) 
                pa = skills.get(pid, None) 
                if ea != cn:
                    skills[aid] = cn
                    modified = True
                    count += 1
                if pid != "None" and pa != cn:
                    skills[pid] = cn
                    modified = True
                    count += 1
            except:
                pass
        if count > 0:
            print(f"Registered {count} skills")
    if modified:
        try:
            with open("../json/skill_ico.json", mode="w", encoding="utf-8") as f:
                json.dump(skills, f, separators=(',',':'))
            print("skill_ico.json updated")
        except Exception as e:
            print("Failed to update skill_ico.json")