package com.xurui.duocodex;

enum Panel {
    TOP("top"), BOTTOM("bottom"), SINGLE("single");

    final String wireName;

    Panel(String wireName) {
        this.wireName = wireName;
    }
}
