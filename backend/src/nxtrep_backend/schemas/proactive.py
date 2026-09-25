from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProactiveFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["helpful", "not_relevant", "inaccurate"]
