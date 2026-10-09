# Uso: make help
ifeq ($(OS),Windows_NT)
  PY_BOOT ?= python
  VPY := .venv/Scripts/python.exe
  RM_RF = if exist $(1) rmdir /s /q $(1)
else
  PY_BOOT ?= python3
  VPY := .venv/bin/python
  RM_RF = rm -rf $(1)
endif

STAMP := .venv/.instalado

.PHONY: help setup run test build clean

help:
	@echo make setup  - crea .venv e instala dependencias de build
	@echo make run    - abre la app desde el codigo fuente
	@echo make test   - ejecuta los tests
	@echo make build  - genera dist/GasLab/, GasLab.exe en Windows
	@echo make clean  - borra build/ y dist/

setup: $(STAMP)

$(STAMP): requirements.txt requirements-build.txt
	$(PY_BOOT) -m venv .venv
	$(VPY) -m pip install -r requirements-build.txt pytest
	$(VPY) -c "open('$(STAMP)','w').close()"

run: $(STAMP)
	$(VPY) graficar.py

test: $(STAMP)
	$(VPY) -m pytest -q test_graficar.py

build: $(STAMP)
	$(VPY) -m PyInstaller --noconfirm --clean GasLab.spec
	@echo Listo: dist/GasLab

clean:
	$(call RM_RF,build)
	$(call RM_RF,dist)
