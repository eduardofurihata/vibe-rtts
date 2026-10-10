.PHONY: run dev test install uninstall setup-mac install-mac uninstall-mac

# macOS uses its own .venv in the project (make setup-mac); Linux reuses the
# vibe-whisper-transcriber venv, which carries the CUDA build of torch.
ifeq ($(shell uname),Darwin)
VENV := $(CURDIR)/.venv
else
VENV := $(HOME)/GitHub/vibe-whisper-transcriber/.venv
endif
SCRIPT := $(CURDIR)/scripts/vibe-rtts.sh
DESKTOP_DIR := $(HOME)/.local/share/applications
DESKTOP_FILE := $(DESKTOP_DIR)/vibe-rtts.desktop
# Themed icon name (freedesktop icon naming spec): follows the user's icon theme
# and keeps `make dev` idempotent against the installed .desktop.
ICON := audio-input-microphone
# macOS app + login agent (make install-mac). launchd runs the app — the bundle is
# only a button that starts the agent: macOS 27 hides the menu bar icon of a
# process owned by an unsigned bundle, but shows it for one launchd started.
MAC_APP := $(HOME)/Applications/Vibe RTTS.app
MAC_AGENT := $(HOME)/Library/LaunchAgents/com.github.furihata.vibe-rtts.plist

run:
	@$(SCRIPT)

dev:
	@mkdir -p $(DESKTOP_DIR)
	@printf '[Desktop Entry]\nType=Application\nName=Vibe RTTS\nComment=Voice-to-text with AI transcription\nExec=$(SCRIPT)\nIcon=$(ICON)\nCategories=Utility;Audio;\nKeywords=voice;transcription;whisper;speech;\nTerminal=false\nStartupNotify=false\n' > $(DESKTOP_FILE)
	@echo "Desktop shortcut created: $(DESKTOP_FILE)"
	@$(SCRIPT)

test:
	@PYTHONPATH=$(CURDIR) $(VENV)/bin/python -m pytest tests/ -v

setup-mac:
	@command -v ffmpeg >/dev/null || brew install ffmpeg
	@uv venv $(VENV) --python 3.12
	@uv pip install --python $(VENV)/bin/python -r requirements-macos.txt
	@echo "Ready: make run (first start downloads the model, ~1.6 GB)"

install-mac:
	@scripts/make-macos-app.sh "$(MAC_APP)"
	@mkdir -p "$(dir $(MAC_AGENT))"
	@printf '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n    <key>Label</key>\n    <string>com.github.furihata.vibe-rtts</string>\n    <key>ProgramArguments</key>\n    <array>\n        <string>$(SCRIPT)</string>\n    </array>\n    <key>RunAtLoad</key>\n    <true/>\n    <key>StandardOutPath</key>\n    <string>$(HOME)/Library/Logs/vibe-rtts.log</string>\n    <key>StandardErrorPath</key>\n    <string>$(HOME)/Library/Logs/vibe-rtts.log</string>\n</dict>\n</plist>\n' > "$(MAC_AGENT)"
	@launchctl bootout gui/$$(id -u) "$(MAC_AGENT)" 2>/dev/null || true
	@launchctl bootstrap gui/$$(id -u) "$(MAC_AGENT)"
	@echo "Installed: $(MAC_APP) (opens at login; logs in ~/Library/Logs/vibe-rtts.log)"

uninstall-mac:
	@launchctl bootout gui/$$(id -u) "$(MAC_AGENT)" 2>/dev/null || true
	@rm -f "$(MAC_AGENT)"
	@pkill -f "python -m vibe_rtts" 2>/dev/null || true
	@rm -rf "$(MAC_APP)"
	@echo "Uninstalled the macOS app and login agent"

install:
	@ln -sf $(SCRIPT) $(HOME)/bin/vibe-rtts
	@chmod +x $(SCRIPT)
	@echo "Installed: ~/bin/vibe-rtts"

uninstall:
	@rm -f $(HOME)/bin/vibe-rtts
	@rm -f $(DESKTOP_FILE)
	@echo "Uninstalled"
