{ lib, stdenv, fetchurl }:

let
  inherit (lib) licenses platforms;
  helpers = import ../lib.nix;
in
stdenv.mkDerivation rec {
  pname = "fixture-tool";
  version = "1.0.0";

  src = fetchurl {
    url = "https://example.com/${pname}-${version}.tar.gz";
    sha256 = "0000000000000000000000000000000000000000000000000000";
  };

  meta = with lib; {
    description = "A fixture tool for testing callPackage extraction";
    homepage = "https://example.com";
    license = licenses.mit;
    platforms = platforms.all;
    maintainers = [];
  };
}
