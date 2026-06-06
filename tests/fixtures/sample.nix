let
  # Named function (lambda bound to name)
  greet = name: "Hello, ${name}!";

  # Multi-arg function (curried)
  add = a: b: a + b;

  # Function taking attrset arg
  mkServer = { host, port ? 8080 }: {
    inherit host port;
    url = "http://${host}:${toString port}";
  };

  # Named attrset
  defaults = {
    timeout = 30;
    retries = 3;
    verbose = false;
  };

  # Inherit from another set
  inherit (defaults) timeout retries;

  # Import
  helpers = import ./helpers.nix;

  # Recursive attrset
  registry = rec {
    version = "1.0.0";
    name = "mypackage";
    fullName = "${name}-${version}";
  };

  # List with path expressions
  modules = [
    ./modules/auth.nix
    ./modules/database.nix
    ./modules/server.nix
  ];

in {
  # Top-level bindings that call local functions
  server = mkServer { host = "localhost"; };
  greeting = greet "world";
  sum = add 1 2;

  # Nested attrset
  config = {
    inherit timeout;
    server = defaults // { verbose = true; };
    modules = modules;
  };

  # With expression
  utils = with helpers; {
    formatted = formatOutput registry;
    validated = validate defaults;
  };

  meta = {
    inherit (registry) name version;
  };
}
