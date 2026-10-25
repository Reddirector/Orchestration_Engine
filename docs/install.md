# Installation

`orchestration-engine` requires Python 3.12 or higher and has **zero runtime dependencies** in its core installation.

## Installing via Pip

```bash
# Core package (zero runtime dependencies)
pip install orchestration-engine

# With optional YAML workflow definition support
pip install "orchestration-engine[yaml]"

# With documentation build tools
pip install "orchestration-engine[docs]"

# With all optional extras
pip install "orchestration-engine[yaml,docs]"
```

## Installing from Source

To install directly from GitHub:

```bash
pip install git+https://github.com/Reddirector/Orchestration_Engine.git
```

For local development:

```bash
git clone https://github.com/Reddirector/Orchestration_Engine.git
cd Orchestration_Engine
uv sync
```

## Verification

Verify that the engine and CLI are installed properly:

```bash
orchestration-engine --help
python -c "import orchestration_engine; print(orchestration_engine.__version__)"
```
