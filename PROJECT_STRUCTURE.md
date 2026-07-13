# Project Structure

```text
SafeMate-AI/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── .streamlit/
│   └── config.toml
├── src/
│   ├── config.py
│   ├── pipeline.py
│   ├── analyzers/
│   │   ├── text_analyzer.py
│   │   ├── url_analyzer.py
│   │   ├── pii_detector.py
│   │   └── file_parser.py
│   ├── services/
│   │   ├── openai_client.py
│   │   ├── file_search.py
│   │   └── web_search.py
│   └── ui/
│       └── components.py
├── data/
│   ├── raw/
│   ├── processed/
│   ├── knowledge_base/
│   └── samples/
├── models/
├── tests/
├── scripts/
└── docs/
```
