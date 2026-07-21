"""TikTok session — persistent login/device sessions."""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from config import Config


@dataclass
class TikTokSession:
    cookies: dict = field(default_factory=dict)
    device_id: str = ''
    is_active: bool = False
    username: str = ''
    nickname: str = ''

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def load_session() -> TikTokSession:
    path = Config.SESSION_FILE
    if path.exists():
        with open(path) as f:
            return TikTokSession.from_dict(json.load(f))
    return TikTokSession()


def save_session(session: TikTokSession):
    path = Config.SESSION_FILE
    with open(path, 'w') as f:
        json.dump(session.to_dict(), f, indent=2)


def clear_session():
    path = Config.SESSION_FILE
    if path.exists():
        path.unlink()
