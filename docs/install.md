# Installation

`orchestration-engine` requires Python 3.12 or higher and has **zero runtime dependencies** in its core installation.

## Standard Installation (Virtual Environment)

On modern Linux distributions (such as Ubuntu 23.04+, Debian 12+, Fedora) adhering to PEP 668, Python environments are managed by the operating system. Always create and activate a virtual environment before installing packages:

```bash
# 1. Create a dedicated virtual environment
python3 -m venv .venv

# 2. Activate the virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install orchestration-engine
pip install orchestration-engine
```

## Optional Extras

```bash
# With optional YAML workflow definition support
pip install "orchestration-engine[yaml]"

# With documentation build tools
pip install "orchestration-engine[docs]"

# With all optional extras
pip install "orchestration-engine[yaml,docs]"
```

## Alternative Package Managers

### Using `uv` (Fastest)

```bash
uv pip install orchestration-engine
```

Or execute the CLI directly without manual installation using `uvx`:

```bash
uvx --from orchestration-engine orchestration-engine --help
```

### Using `pipx` (For Global CLI Tooling)

If you wish to use the `orchestration-engine` CLI globally without managing project virtual environments:

```bash
pipx install orchestration-engine
```

## Installing from Source

To install the bleeding-edge development version directly from GitHub:

```bash
pip install git+https://github.com/Reddirector/Orchestration_Engine.git
```

For local engine development:

```bash
git clone https://github.com/Reddirector/Orchestration_Engine.git
cd Orchestration_Engine
uv sync
```

## Verification

Verify that the engine and CLI are installed properly:

```bash
# Check CLI binary
orchestration-engine --help

# Verify Python import and version
python -c "import orchestration_engine; print(f'v{orchestration_engine.__version__}')"
```
