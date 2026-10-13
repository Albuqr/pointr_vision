import React from "react";
import { createRoot } from "react-dom/client";
import StudioApp from "./studio";
import "./style.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing root element");
createRoot(root).render(<React.StrictMode><StudioApp /></React.StrictMode>);
