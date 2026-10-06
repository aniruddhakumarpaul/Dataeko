.PHONY: setup data train eval test run
PYTHON ?= python

setup:
	$(PYTHON) -m pip install -r requirements-lock.txt

data:
	$(PYTHON) scripts/generate_synthetic_data.py

train:
	$(PYTHON) scripts/train_classifier.py

eval: train
	$(PYTHON) scripts/evaluate.py

test: train
	$(PYTHON) -m pytest

run: train
	$(PYTHON) -m streamlit run app.py
