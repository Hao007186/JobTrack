from pydantic import BaseModel


class AirportOut(BaseModel):
    iata: str
    name_zh: str
    city_zh: str
    country: str
    is_origin: bool


class AirlineOut(BaseModel):
    iata: str
    name_zh: str
