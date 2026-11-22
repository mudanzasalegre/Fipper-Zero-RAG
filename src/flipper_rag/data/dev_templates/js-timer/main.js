// The Flipper mJS engine requires event_loop for timers.
let eventLoop = require("event_loop");
let timer = eventLoop.timer("oneshot", 1000);
eventLoop.subscribe(timer, function(_subscription, _event, loop) {
    print("Timer elapsed");
    loop.stop();
}, eventLoop);
eventLoop.run();
