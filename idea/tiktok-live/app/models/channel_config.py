"""Channel configuration — non-sensitive one-time setup fields."""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from config import Config


@dataclass
class ChannelConfig:
    title: str = 'My Live Stream'
    game_id: str = ''
    game_name: str = ''
    topic_id: str = ''
    topic_name: str = ''
    extras: list = field(default_factory=list)
    extra_names: list = field(default_factory=list)
    is_setup_done: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def load_channel_config() -> ChannelConfig:
    path = Config.CHANNEL_CONFIG_FILE
    if path.exists():
        with open(path) as f:
            return ChannelConfig.from_dict(json.load(f))
    return ChannelConfig()


def save_channel_config(config: ChannelConfig):
    path = Config.CHANNEL_CONFIG_FILE
    with open(path, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)
