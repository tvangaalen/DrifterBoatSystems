// Entry point (index.html loads it as a module): the core, then the pages in the order of the navigation, then start.
import Drifter from "./core/app.js";
import "./energy.js";
import "./anchor.js";
import "./guard.js";
import "./washer.js";
import "./enginelog.js";

Drifter.start();
