# WhatsApp-Telegram Bridge

A bidirectional messaging bridge that seamlessly connects WhatsApp and Telegram, enabling real-time communication between the two platforms. Built with Python, Playwright for browser automation, and aiogram for Telegram bot integration, this project supports multiple WhatsApp accounts concurrently in a Docker containerized environment.

## Project Overview

This bridge allows users to send and receive messages between WhatsApp and Telegram chats. It leverages browser automation to interact with WhatsApp Web and uses Telegram's Bot API for message forwarding. The system is designed for reliability with adaptive polling, error handling, and persistent state management.

## Features

- **Bidirectional Messaging**: Send and receive text messages between WhatsApp and Telegram
- **Media Support**: Handle images, documents, and other media files with full-resolution extraction
- **Message Threading**: Maintain conversation context and correlation between platforms
- **Real-time Delivery**: Instant message delivery with confirmation status
- **Adaptive Polling**: Fibonacci backoff strategy for efficient resource usage
- **Multi-Account Support**: Concurrent handling of up to 2 WhatsApp accounts
- **Error Handling**: Comprehensive diagnostics and automatic recovery mechanisms
- **Docker Deployment**: Containerized with persistent storage and hot-reload capabilities
- **Environment Configuration**: Secure, flexible configuration via environment variables

## Architecture

The bridge operates using an asyncio-based architecture with three concurrent tasks:
- Two WhatsApp listeners for multi-account support
- One Telegram bot handler

It implements a producer-consumer pattern with message queues for efficient message routing. Browser automation via Playwright manages WhatsApp Web interactions, while aiogram handles Telegram Bot API communications. State is persisted in JSON format, and an adaptive delay system optimizes resource consumption.

## Installation

### Prerequisites

- Docker and Docker Compose installed
- Python 3.8+ (for local development)
- A Telegram bot token from [@BotFather](https://t.me/botfather)

### Quick Start with Docker

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Whtpp-Tlgm-bridge
   ```

2. Create environment file:
   ```bash
   cp .env.example .env
   ```

3. Configure your environment variables (see Configuration section)

4. Start the bridge:
   ```bash
   docker-compose up -d
   ```

### Local Development

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install Playwright browsers:
   ```bash
   playwright install
   ```

3. Run the bridge:
   ```bash
   python bridge.py
   ```

## Configuration

Create a `.env` file in the project root with the following variables:

```env
# Telegram Configuration
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_target_chat_id_here

# Browser Configuration
HEADLESS=true

# WhatsApp Configuration (auto-generated on first run)
# Session data stored in persistent volumes
```

### Environment Variables

- `TELEGRAM_TOKEN`: Token obtained from [@BotFather](https://t.me/botfather)
- `TELEGRAM_CHAT_ID`: ID of the Telegram chat to bridge messages to
- `HEADLESS`: Set to `true` for headless browser mode (recommended for production)

## Usage

1. **First Run Setup**:
   - Start the container
   - Access WhatsApp Web via the browser automation
   - Scan QR codes for each WhatsApp account
   - Sessions are automatically saved for future runs

2. **Sending Messages**:
   - Messages from WhatsApp are automatically forwarded to the configured Telegram chat
   - Messages from Telegram are sent to all linked WhatsApp accounts

3. **Media Handling**:
   - Images and documents are downloaded and forwarded between platforms
   - Full-resolution images are extracted (not thumbnails)

4. **Monitoring**:
   - Check container logs for real-time status
   ```bash
   docker-compose logs -f bridge
   ```

## Troubleshooting

### Common Issues

1. **QR Code Scanning Issues**:
   - Ensure stable internet connection
   - Try restarting the container
   - Check browser logs for errors

2. **Message Delivery Failures**:
   - Verify Telegram token and chat ID
   - Check network connectivity
   - Review container logs for specific error messages

3. **High Resource Usage**:
   - Adjust polling intervals in the code
   - Monitor adaptive delay system logs

4. **Session Expiration**:
   - WhatsApp sessions may expire; re-scan QR codes
   - Persistent volumes maintain session data between container restarts

### Logs and Diagnostics

Enable debug logging by setting environment variable:
```env
LOG_LEVEL=DEBUG
```

Access logs:
```bash
docker-compose logs bridge
```

## Development

### Project Structure

```
Whtpp-Tlgm-bridge/
├── bridge.py              # Main application logic
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container build configuration
├── docker-compose.yml    # Orchestration configuration
├── .dockerignore         # Docker ignore patterns
├── .gitignore           # Git ignore patterns
└── README.md             # This file
```

### Key Components

- **bridge.py**: Core bridge logic with asyncio tasks, message queues, and browser automation
- **Dockerfile**: Multi-stage build for optimized container size
- **docker-compose.yml**: Service orchestration with persistent volumes

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

### Testing

Run tests locally:
```bash
python -m pytest tests/
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

For additional information, refer to the documentation files:
- [Hoja de Ruta de Desarrollo](Hoja de Ruta de Desarrollo_ Puente de Mensajería WhatsApp-Telegram.md)
- [Plan Técnico](Plan Técnico_ Puente de Mensajería WhatsApp-Telegram.md)