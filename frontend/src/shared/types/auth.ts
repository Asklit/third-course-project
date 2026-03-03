export type LoginRequest = {
  email: string;
  password: string;
};

export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
};
