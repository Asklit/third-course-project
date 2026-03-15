import { apiClient } from "../../../shared/api/client";

type LogoutRequest = {
  refresh_token: string;
};

type LogoutResponse = {
  status: "logged_out";
};

export function logoutStudent(payload: LogoutRequest) {
  return apiClient<LogoutResponse>("/auth/logout", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
