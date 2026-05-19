from pydantic import BaseModel


class FinalReport(BaseModel):
    title: str
    markdown: str

