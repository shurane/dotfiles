from pydantic import BaseModel, ConfigDict, Field


class QbittorrentPreferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    web_ui_username: str


class QbittorrentSetPreferencesRequest(BaseModel):
    web_ui_username: str
    web_ui_password: str


class ArcaneLoginRequest(BaseModel):
    username: str
    password: str


class ArcaneUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    username: str = Field(min_length=1)


class ArcaneResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: ArcaneUser | None = None


class ArcanePasswordRequest(BaseModel):
    current_password: str = Field(serialization_alias="currentPassword")
    new_password: str = Field(serialization_alias="newPassword")


class ArcaneUpdateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str = Field(serialization_alias="displayName")
    email: str


class JellyfinUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="Id", min_length=1)
    name: str = Field(alias="Name", min_length=1)


class JellyfinAuthRequest(BaseModel):
    username: str = Field(serialization_alias="Username")
    password: str = Field(serialization_alias="Pw")


class JellyfinAuthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user: JellyfinUser = Field(alias="User")
    access_token: str = Field(alias="AccessToken", min_length=1)
