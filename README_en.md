# NagaAgent

[简体中文](README.md)|[繁體中文](README_tw.md)|[English](README_en.md)

![NagaAgent Logo](https://img.shields.io/badge/NagaAgent-4.0-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge)

![Star History](https://img.shields.io/github/stars/Xxiii8322766509/NagaAgent?style=social)![Forks](https://img.shields.io/github/forks/Xxiii8322766509/NagaAgent?style=social)![Issues](https://img.shields.io/github/issues/Xxiii8322766509/NagaAgent)![Pull Requests](https://img.shields.io/github/issues-pr/Xxiii8322766509/NagaAgent)
![UI Preview](ui/img/README.jpg)
---

## [Get Tutorial Videos and One-Click Runner Package Here](https://www.pylindex.top/naga)


## Introduction

NagaAgent is a feature-rich intelligent conversational assistant system with the following special features:

### 🎯 Core Features
- **Intelligent Dialogue System**: Supports streaming conversations and tool-calling loops
- **Multi-Agent Collaboration**: Intelligent task scheduling based on game theory
- **Knowledge Graph Memory**: GRAG system supports long-term memory and intelligent retrieval
- **Full Voice Interaction**: Real-time voice input and output processing
- **Modern Interface**: PyQt5 GUI + Live2D virtual avatar
- **System Tray Integration**: Background operation and quick actions

### 🛠️ Technical Architecture

#### System Overall Architecture
```mermaid
graph TB
    %% UI Layer
    subgraph "UI Layer"
        UI[PyQt5 GUI Interface]
        Live2D[Live2D Virtual Avatar]
        Tray[System Tray]
        Chat[Chat Interface]
    end

    %% Core Services
    subgraph "Core Services"
        API[API Server<br/>:8000]
        Agent[Agent Server<br/>:8001]
        MCP[MCP Server<br/>:8003]
        TTS[TTS Server<br/>:5048]
    end

    %% Business Logic
    subgraph "Business Logic Layer"
        Game[Game Theory System<br/>Multi-Agent Collaboration]
        Memory[GRAG Memory System<br/>Knowledge Graph]
        Voice[Voice Processing System<br/>Real-time Voice Interaction]
        Tools[Tool Calling System<br/>MCP Protocol]
    end

    %% Data Storage
    subgraph "Data Storage Layer"
        Neo4j[(Neo4j Graph Database<br/>Knowledge Graph Storage)]
        Files[File System<br/>Config/Logs/Cache]
        MemoryCache[In-memory Cache<br/>Session State]
    end

    %% External Services
    subgraph "External Services Layer"
        LLM[LLM Providers<br/>OpenAI/Qwen, etc.]
        Portal[NagaPortal<br/>Portal Service]
        MQTT[IoT Devices<br/>MQTT Communication]
        Web[Web Crawler<br/>Online Search]
    end

    %% Connections
    UI --> API
    UI --> Agent
    UI --> MCP
    UI --> TTS

    API --> Game
    API --> Memory
    API --> Voice
    API --> Tools

    Agent --> Game
    Agent --> Tools

    MCP --> Tools
    MCP --> Portal
    MCP --> MQTT
    MCP --> Web

    TTS --> Voice

    Game --> Memory
    Memory --> Neo4j
    Voice --> LLM
    Tools --> LLM

    API --> MemoryCache
    Agent --> MemoryCache
    MCP --> MemoryCache

    %% Styles
    classDef uiLayer fill:#e1f5fe
    classDef coreLayer fill:#f3e5f5
    classDef businessLayer fill:#e8f5e8
    classDef dataLayer fill:#fff3e0
    classDef externalLayer fill:#fce4ec

    class UI,Live2D,Tray,Chat uiLayer
    class API,Agent,MCP,TTS coreLayer
    class Game,Memory,Voice,Tools businessLayer
    class Neo4j,Files,MemoryCache dataLayer
    class LLM,Portal,MQTT,Web externalLayer

```

#### Core Characteristics
- **Multi-Service Parallelism**: API Server (8000), Agent Server (8001), MCP Server (8003), TTS Server (5048)
- **Modular Design**: Each service runs independently and supports hot-swapping
- **Configuration-Driven**: Real-time configuration hot-reloading without restart
- **Cross-Platform Support**: Windows, macOS, Linux

### 🔧 Tech Stack

#### Tech Stack Architecture
```mermaid
graph TB
    %% Frontend Stack
    subgraph "Frontend Stack"
        PyQt5[PyQt5<br/>GUI Framework]
        Live2D[Live2D<br/>Virtual Avatar]
        QSS[QSS<br/>Stylesheet]
    end

    %% Backend Stack
    subgraph "Backend Stack"
        FastAPI[FastAPI<br/>Web Framework]
        Uvicorn[Uvicorn<br/>ASGI Server]
        AsyncIO[AsyncIO<br/>Asynchronous Programming]
    end

    %% Database Stack
    subgraph "Database Stack"
        Neo4j[Neo4j<br/>Graph Database]
        GRAG[GRAG<br/>Knowledge Graph]
        Memory[In-memory Cache<br/>Session Management]
    end

    %% AI Stack
    subgraph "AI Stack"
        OpenAI[OpenAI API<br/>GPT Models]
        Qwen[Qwen<br/>Multimodal Models]
        MCP[MCP Protocol<br/>Tool Calling]
    end

    %% Voice Stack
    subgraph "Voice Stack"
        ASR[Speech Recognition<br/>ASR]
        TTS[Text-to-Speech<br/>TTS]
        Realtime[Real-time Voice<br/>WebRTC]
    end

    %% Network Stack
    subgraph "Network Stack"
        HTTP[HTTP/HTTPS<br/>RESTful API]
        WebSocket[WebSocket<br/>Real-time Communication]
        MQTT[MQTT<br/>IoT Protocol]
    end

    %% Styles
    classDef frontend fill:#e3f2fd
    classDef backend fill:#f1f8e9
    classDef database fill:#fff3e0
    classDef ai fill:#fce4ec
    classDef voice fill:#e8f5e8
    classDef network fill:#f3e5f5

    class PyQt5,Live2D,QSS frontend
    class FastAPI,Uvicorn,AsyncIO backend
    class Neo4j,GRAG,Memory database
    class OpenAI,Qwen,MCP ai
    class ASR,TTS,Realtime voice
    class HTTP,WebSocket,MQTT network
```

#### Core Technologies
- **Python 3.11** + PyQt5 + FastAPI
- **Neo4j Graph Database** + GRAG Knowledge Graph
- **MCP (Model Context Protocol)** for Tool Calling
- **OpenAI-Compatible API** + Support for multiple LLM providers


---

## Deployment and Running Tutorial

### System Requirements
- Python 3.11
- Optional: `uv` tool (for faster dependency installation, without needing a specific Python version)

### Quick Start

>  If you encounter difficulties with deployment, please refer to the video tutorial or download the one-click runner package.

#### 1. Install Dependencies
##### Using the setup script

```bash
# Optional: Install uv first
pip install uv

# Use setup.py to initialize automatically
python setup.py

# Or use setup.sh (Linux/macOS)
./setup.sh

# Or use setup.bat (Windows)
setup.bat
```

The initialization script will automatically:
- Check the Python version
- Create a virtual environment
- Install required packages
- Copy the configuration file template
- Open the configuration file for editing
</details>

<details><summary>Manual Deployment</summary>

```bash
# Without uv
python -m venv .venv

# Linux/macOS
source .venv/bin/activate
# Windows
.\.venv\Scripts\activate

pip install -r requirements.txt

# With uv
uv sync
```
</details>

#### 2. Configure LLM API
Edit the `config.json` file and configure your LLM API information:
```json
{
  "api": {
    "api_key": "your_api_key",
    "base_url": "model_provider_openai_api_endpoint",
    "model": "model_name"
  }
}
```

<details><summary>Optional Configuration</summary>

#### Enable Knowledge Graph Memory

Install `neo4j` using `docker` or install `Neo4j Desktop`, then configure the Neo4j connection parameters in `config.json`:
```json
{
  "grag": {
    "enabled": true,
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "the_password_you_set_during_neo4j_installation"
  }
}
```

#### Enable Voice Output Function
```json
{
  "system": {
    "voice_enabled": true
  },
  "tts": {
    "port": 5048
  }
}
```

#### Live2D Related Configuration

```json5
  "live2d": {
    "enabled": false, // Whether to enable Live2D
    "model_path": "ui/live2d/live2d_models/characters/llny/mianfeimox/llny.model3.json", // Live2D model path
    "fallback_image": "ui/img/standby.png", // Fallback image
    "auto_switch": true, // Whether to switch automatically
    "animation_enabled": true, // Whether to enable animation
    "touch_interaction": true // Whether to enable touch interaction
  },
  ```

> For other configuration options, please refer to the comments in the file.

</details>

#### 3. Start the Application
```bash
# Using the start script
./start.sh          # Linux/macOS
start.bat           # Windows


# Or run the py file directly
# Linux/macOS
source .venv/bin/activate
# Windows
.\.venv\Scripts\activate
python main.py

# uv
uv run main.py
```


<details><summary>Troubleshooting</summary>

1.  **Incompatible Python Version**: Ensure you are using Python 3.11
2.  **Port in Use**: Check if ports 8000, 8001, 8003, and 5048 are available
3.  **Neo4j Connection Failed**: Make sure the Neo4j service is running
4.  **JSON parsing error when checking Neo4j connection**: Exit and restart the program
5.  **Unknown Errors**: Please create an issue to provide feedback

</details>

<details><summary>Environment Check</summary>

```bash
# Run system environment check
python main.py --check-env --force-check

# Quick check
python main.py --quick-check
```

</details>


## License

[NagaAgent License](LICENSE)


## Contributing

Issues and Pull Requests are welcome!

<details><summary>Build a One-Click Runner Package</summary>

```bash
python build.py
```
The built files are located in the `dist/` directory.

</details>


<div align="center">

**Thank you to all developers who have contributed to this project**

**⭐ If this project is helpful to you, please consider giving us a Star**

</div>
