import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/noto-sans-kr/korean-400.css";
import "@fontsource/noto-sans-kr/korean-500.css";
import "@fontsource/noto-sans-kr/korean-600.css";
import "@fontsource/noto-sans-kr/korean-700.css";
import App from "./App";
import LiveApp from "./LiveApp";
import { demo } from "./api";
import "./styles.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {demo ? <App /> : <LiveApp />}
  </React.StrictMode>,
);
