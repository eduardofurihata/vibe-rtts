.PHONY: run install uninstall

VENV := $(HOME)/GitHub/vibe-whisper-transcriber/.venv
SCRIPT := $(CURDIR)/scripts/vibe-rtts.sh

run:
	@$(SCRIPT)

install:
	@ln -sf $(SCRIPT) $(HOME)/bin/vibe-rtts
	@chmod +x $(SCRIPT)
	@echo "Installed: ~/bin/vibe-rtts"

uninstall:
	@rm -f $(HOME)/bin/vibe-rtts
	@echo "Uninstalled"
