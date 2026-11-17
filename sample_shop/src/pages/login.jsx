import React from "react";
import { loginUser } from "../api/authClient";

function LoginPage() {
  function handleSubmit(e) { loginUser(); }
  return null;
}
export default LoginPage;
