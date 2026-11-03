from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProactiveFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["helpful", "not_relevant", "inaccurate"]


class ProactiveSnoozeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    until: datetime
