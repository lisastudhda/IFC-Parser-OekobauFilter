# 🚀 Anleitung: App kostenlos online veröffentlichen mit Streamlit Community Cloud

Mit Streamlit läuft dein Projekt auf einem echten Cloud-Server, sodass **`IfcOpenShell`** und alle Funktionen zu 100% genau wie auf deinem Mac funktionieren.

---

## Schritt 1: Projektordner auf GitHub hochladen

Führe in deinem Terminal (im Ordner `ifc-lca-analysis`) folgende Befehle aus:

```bash
git add .
git commit -m "Add Streamlit app and requirements for deployment"
git push origin main
```

*(Falls du den Code manuell über die GitHub-Website hochlädst: Lade einfach alle Dateien und Ordner inklusive `app.py` und `requirements.txt` hoch).*

---

## Schritt 2: Auf Streamlit Cloud aktivieren

1. Gehe im Browser auf **[share.streamlit.io](https://share.streamlit.io/)**.
2. Klicke auf **"Sign in with GitHub"** und autorisiere Streamlit mit deinem GitHub-Konto.
3. Klicke oben rechts auf die Schaltfläche **"New app"** (bzw. "Create app").
4. Wähle dein GitHub-Repository aus:
   - **Repository:** `<dein-nutzername>/ifc-lca-analysis`
   - **Branch:** `main` (oder `master`)
   - **Main file path:** `app.py`
5. Klicke auf **"Deploy!"**.

---

## 🎉 Fertig!

Nach ca. 1–2 Minuten ist deine Webanwendung live unter einer öffentlichen URL (z. B. `https://ifc-lca-analysis.streamlit.app`) erreichbar. 

Jedes Mal, wenn du in Zukunft Code auf GitHub pushst, aktualisiert sich die Online-App automatisch!
