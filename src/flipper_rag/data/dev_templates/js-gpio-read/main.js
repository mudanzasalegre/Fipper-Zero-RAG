// Read-only GPIO example; consult pinout and voltage levels before connecting hardware.
let eventLoop = require("event_loop");
let gpio = require("gpio");
let pin = gpio.get("pc3");
pin.init({ direction: "in", inMode: "plain_digital" });
print("Pin PC3:", pin.read());
