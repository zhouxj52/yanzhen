import View from "./view.js";
import Controller from "./controller.js";
import Model from "./model.js";
import Store from "./store.js";
import Template from "./template.js";





let todo;
const onHashChange = () => {
    todo.controller.setView(document.location.hash);
};

const onLoad = () => {
    todo = new Todo("javascript-es6-webpack");
    onHashChange();
};

function Todo(name) {
    this.storage = new Store(name);
    this.model = new Model(this.storage);
    this.template = new Template();
    this.view = new View(this.template);
    this.controller = new Controller(this.model, this.view);
}

window.addEventListener("load", onLoad);
window.addEventListener("hashchange", onHashChange);
