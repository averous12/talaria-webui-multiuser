/* Small compatibility layer for browsers older than Chrome 110. */
(function () {
  "use strict";

  if (typeof AbortSignal.any !== "function") {
    AbortSignal.any = function (signals) {
      var controller = new AbortController();
      var removers = [];
      var finish = function (signal) {
        if (controller.signal.aborted) return;
        controller.abort(signal.reason);
        for (var i = 0; i < removers.length; i++) removers[i]();
        removers = [];
      };
      for (var i = 0; i < signals.length; i++) {
        var signal = signals[i];
        if (signal.aborted) {
          finish(signal);
          break;
        }
        var listener = function (source) {
          return function () { finish(source); };
        }(signal);
        signal.addEventListener("abort", listener, { once: true });
        removers.push(function (source, handler) {
          return function () { source.removeEventListener("abort", handler); };
        }(signal, listener));
      }
      return controller.signal;
    };
  }

  if (typeof Array.prototype.toSorted !== "function") {
    Object.defineProperty(Array.prototype, "toSorted", {
      configurable: true,
      writable: true,
      value: function (compareFn) { return this.slice().sort(compareFn); },
    });
  }

  if (typeof Array.prototype.toReversed !== "function") {
    Object.defineProperty(Array.prototype, "toReversed", {
      configurable: true,
      writable: true,
      value: function () { return this.slice().reverse(); },
    });
  }
})();
