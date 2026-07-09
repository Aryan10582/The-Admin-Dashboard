export type ApiResponse<T> = {
  success: boolean;
  data: T;
};

export type Admin = {
  id: string;
  email: string;
  username: string | null;
};

export type AuthPayload = {
  admin: Admin;
};
