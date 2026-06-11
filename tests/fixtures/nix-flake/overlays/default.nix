final: prev:

{
  customTool = prev.hello.overrideAttrs (old: {
    pname = "custom-tool";
    version = "2.0.0";
  });

  myLib = prev.lib.extend (libFinal: libPrev: {
    myHelper = x: x + 1;
  });
}
