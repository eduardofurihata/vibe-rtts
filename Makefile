.PHONY: run dev test install uninstall

VENV := $(HOME)/GitHub/vibe-whisper-transcriber/.venv
SCRIPT := $(CURDIR)/scripts/vibe-rtts.sh
DESKTOP_DIR := $(HOME)/.local/share/applications
DESKTOP_FILE := $(DESKTOP_DIR)/vibe-rtts.desktop
ICON := $(CURDIR)/vibe_rtts/icons/mic-active.png

run:
	@$(SCRIPT)

dev:
	@mkdir -p $(DESKTOP_DIR)
	@printf '[Desktop Entry]\nType=Application\nName=Vibe RTTS\nComment=Voice-to-text with AI transcription\nExec=$(SCRIPT)\nIcon=$(ICON)\nCategories=Utility;Audio;\nKeywords=voice;transcription;whisper;speech;\nTerminal=false\nStartupNotify=false\n' > $(DESKTOP_FILE)
	@echo "Desktop shortcut created: $(DESKTOP_FILE)"
	@$(SCRIPT)

test:
	@PYTHONPATH=$(CURDIR) $(VENV)/bin/python -m pytest tests/ -v

install:
	@ln -sf $(SCRIPT) $(HOME)/bin/vibe-rtts
	@chmod +x $(SCRIPT)
	@echo "Installed: ~/bin/vibe-rtts"

uninstall:
	@rm -f $(HOME)/bin/vibe-rtts
	@rm -f $(DESKTOP_FILE)
	@echo "Uninstalled"
