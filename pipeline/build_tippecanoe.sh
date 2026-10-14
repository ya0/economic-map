# Builds tippecanoe (with a local static sqlite, no sudo needed) under data/raw/tippecanoe_build; run inside WSL: wsl bash pipeline/build_tippecanoe.sh
set -e
cd "$(dirname "$0")/../data/raw"
mkdir -p tippecanoe_build && cd tippecanoe_build
[ -d tippecanoe ] || git clone --depth 1 https://github.com/felt/tippecanoe.git
[ -f sqlite-amalgamation-3460000.zip ] || curl -sSLO https://www.sqlite.org/2024/sqlite-amalgamation-3460000.zip
[ -d sqlite-amalgamation-3460000 ] || unzip -q sqlite-amalgamation-3460000.zip
cd sqlite-amalgamation-3460000
[ -f libsqlite3.a ] || { gcc -O2 -c sqlite3.c -o sqlite3.o && ar rcs libsqlite3.a sqlite3.o; }
cd ../tippecanoe
SQ=$(realpath ../sqlite-amalgamation-3460000)
make -j8 CXXFLAGS="-I$SQ" CFLAGS="-I$SQ" LDFLAGS="-L$SQ" >/dev/null
ls -la tippecanoe
