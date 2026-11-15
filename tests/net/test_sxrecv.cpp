#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <io.h>
#include "s2r_net.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using s2r::js::V;
using s2r::proto::SaveXfer;
namespace proto = s2r::proto;

static void require(bool ok, const char* what)
{
    if (!ok) throw std::runtime_error(what);
}
static void put(const fs::path& p, const std::string& data)
{
    std::ofstream f(p, std::ios::binary);
    f.write(data.data(), (std::streamsize)data.size());
    f.close();
    require(!f.fail(), "fixture write failed");
}
static std::string get(const fs::path& p)
{
    std::ifstream f(p, std::ios::binary);
    require(f.is_open(), "expected output file missing");
    std::ostringstream out;
    out << f.rdbuf();
    return out.str();
}
struct Handle
{
    HANDLE h = INVALID_HANDLE_VALUE;
    ~Handle() { close(); }
    void close()
    {
        if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
        h = INVALID_HANDLE_VALUE;
    }
};
// Locate only this fixture's CRT handle, without accessing SaveXfer internals.
// Invalidating it produces a real I/O failure even though MSVC fopen_s denies
// external file opens (and Wine does not enforce all byte-range locks).
static HANDLE part_handle(const fs::path& path)
{
    struct InvalidParameterGuard
    {
        _invalid_parameter_handler old = _set_invalid_parameter_handler(
            [](const wchar_t*, const wchar_t*, const wchar_t*, unsigned int, uintptr_t) {});
        ~InvalidParameterGuard() { _set_invalid_parameter_handler(old); }
    } guard;
    std::wstring suffix = L"\\" + path.parent_path().filename().wstring() + L"\\" + path.filename().wstring();
    for (int fd = 0; fd < _getmaxstdio(); ++fd)
    {
        intptr_t raw = _get_osfhandle(fd);
        if (raw == -1 || raw == -2) continue;
        wchar_t name[32768];
        DWORD n = GetFinalPathNameByHandleW((HANDLE)raw, name, 32768, FILE_NAME_NORMALIZED);
        if (n >= suffix.size() && n < 32768 && _wcsicmp(name + n - suffix.size(), suffix.c_str()) == 0)
            return (HANDLE)raw;
    }
    throw std::runtime_error("fixture part file handle was not found");
}
struct Fixture
{
    fs::path dir;
    std::string payload = "abcdefghij";
    uint64_t id = 42, ch = 4;
    std::vector<std::string> sent;
    SaveXfer::Say say = [](const std::string&) {};
    SaveXfer::Send send = [&](const std::string& data) { sent.push_back(data); };
    std::unique_ptr<SaveXfer> sx;
    Fixture()
    {
        static unsigned seq = 0;
        dir = fs::temp_directory_path() / ("nola_sxrecv_" + std::to_string(GetCurrentProcessId()) + "_" + std::to_string(++seq));
        fs::create_directories(dir);
    }
    ~Fixture()
    {
        sx.reset();
        std::error_code ec;
        fs::remove_all(dir, ec);
    }
    uint64_t n() const { return (payload.size() + ch - 1) / ch; }
    void start()
    {
        put(dir / "sx_want.txt", std::to_string(id));
        sx = std::make_unique<SaveXfer>(dir.wstring(), [&](const std::string& s) { say(s); });
        sx->tick(100, send);
        info();
    }
    void info()
    {
        V obj = V::Object();
        obj.set("id", V::Str(std::to_string(id)));
        obj.set("st", V::Str("ok"));
        obj.set("size", V::Int((int64_t)payload.size()));
        obj.set("crc", V::Int(s2r::z::crc32(payload)));
        obj.set("ch", V::Int((int64_t)ch));
        sx->feed(proto::pack(proto::T_SXI, obj), send);
    }
    std::string chunk(uint32_t i) const
    {
        std::string data = "S2";
        data.push_back((char)proto::PROTO);
        data.push_back((char)proto::T_SXC);
        for (unsigned b = 0; b < 8; ++b) data.push_back((char)(id >> (8 * b)));
        for (unsigned b = 0; b < 4; ++b) data.push_back((char)(i >> (8 * b)));
        data += payload.substr((size_t)i * ch, (size_t)ch);
        return data;
    }
    void feed(const std::string& data) { sx->feed(data, send); }
    void all()
    {
        for (uint32_t i = 0; i < n(); ++i) feed(chunk(i));
    }
    void checkpoint(const std::string& bits, const std::string& contents)
    {
        put(dir / "sx_in.part", contents);
        put(dir / "sx_in.map", std::to_string(id) + " " + std::to_string(payload.size()) + " " +
            std::to_string(s2r::z::crc32(payload)) + " " + std::to_string(ch) + "\n" + bits);
    }
    void complete()
    {
        require(sx->stats.done == 1, "transfer did not complete exactly once");
        require(get(dir / "sx_in.pkg") == payload, "published package differs from sender");
        sx->tick(110, send);
        require(sx->stats.done == 1, "completed transfer was published twice");
    }
};

static void reorder_duplicate()
{
    Fixture f;
    f.start();
    f.feed(f.chunk(2));
    f.feed(f.chunk(0));
    auto duplicate = f.chunk(0);
    duplicate.back() ^= 1;
    f.feed(duplicate);
    f.feed(f.chunk(1));
    f.complete();
    require(f.sx->stats.recv == 3, "duplicate counted as a new chunk");
}
static void lengths()
{
    Fixture f;
    f.start();
    auto short_chunk = f.chunk(0);
    short_chunk.pop_back();
    f.feed(short_chunk);
    f.feed(f.chunk(1) + "overflow");
    f.feed(f.chunk(2) + "x");
    f.feed(f.chunk(0).substr(0, 16));
    require(f.sx->stats.recv == 0, "malformed payload was accepted");
    f.sx->tick(101, f.send);
    f.all();
    f.complete();
}
static void headers()
{
    Fixture f;
    f.start();
    for (size_t len = 0; len < 16; ++len) f.feed(f.chunk(0).substr(0, len));
    auto bad = f.chunk(0);
    bad[0] = '?';
    f.feed(bad);
    bad = f.chunk(0);
    bad[2] = (char)(proto::PROTO + 1);
    f.feed(bad);
    bad = f.chunk(0);
    bad[4] = 43;
    f.feed(bad);
    bad = f.chunk(0);
    bad[12] = 100;
    f.feed(bad);
    require(f.sx->stats.recv == 0, "bad header or foreign chunk was accepted");
    f.all();
    f.complete();
}
static void rename_retry()
{
    Fixture f;
    Handle lock;
    f.start();
    put(f.dir / "sx_in.pkg", "previous package");
    lock.h = CreateFileW((f.dir / "sx_in.pkg").c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    require(lock.h != INVALID_HANDLE_VALUE, "could not lock destination");
    bool threw = false;
    try { f.all(); } catch (const std::exception&) { threw = true; }
    require(threw && f.sx->stats.done == 0, "locked destination was not reported");
    require(get(f.dir / "sx_in.pkg") == "previous package", "failed transfer changed previous package");
    lock.close();
    f.sx->tick(102, f.send);
    f.complete();
}
static void resume_complete()
{
    Fixture f;
    f.checkpoint(std::string((size_t)f.n(), 1), f.payload);
    f.start();
    f.sx->tick(101, f.send);
    f.complete();
    require(f.sx->stats.recv == 0, "complete checkpoint was downloaded again");
}
static void resume_partial()
{
    Fixture f;
    f.start();
    f.feed(f.chunk(0));
    f.sx->tick(101, f.send);
    f.sx.reset();
    f.start();
    f.feed(f.chunk(2));
    f.feed(f.chunk(1));
    f.complete();
    require(f.sx->stats.recv == 2, "valid checkpoint was discarded");
}
static void bad_bitmap()
{
    Fixture f;
    f.checkpoint(std::string((size_t)f.n(), 2), f.payload);
    f.start();
    f.all();
    f.complete();
    require(f.sx->stats.recv == f.n(), "invalid bitmap was trusted");
}
static void empty_package()
{
    Fixture f;
    f.payload.clear();
    f.start();
    f.sx->tick(101, f.send);
    f.complete();
}
static void crc_reopen_failure()
{
    Fixture f;
    Handle lock;
    f.payload = "x";
    f.say = [&](const std::string& s)
    {
        if (s.find("CRC32 bad") == std::string::npos) return;
        lock.h = CreateFileW((f.dir / "sx_in.part").c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        require(lock.h != INVALID_HANDLE_VALUE, "could not block CRC recovery reopen");
    };
    f.start();
    auto bad = f.chunk(0);
    bad.back() = 'y';
    bool threw = false;
    try { f.feed(bad); } catch (const std::exception&) { threw = true; }
    require(threw && f.sx->stats.crcbad == 1, "CRC recovery failure was not exercised");
    lock.close();
    f.sent.clear();
    f.sx->tick(102, f.send);
    bool asks_info = false;
    for (const auto& packet : f.sent)
    {
        uint8_t type;
        V obj;
        std::string error;
        if (proto::unpack(packet, type, obj, error) == proto::Unpack::ok && type == proto::T_SXW)
        {
            const V* ranges = obj.get("r");
            asks_info = ranges && ranges->t == V::array && ranges->a.size() == 1 &&
                ranges->a[0].a.size() == 2 && s2r::js::dumps(ranges->a[0].a[1], false) == "63";
        }
    }
    require(asks_info, "failed reopen left receiver active with no file handle");
    f.info();
    f.all();
    f.complete();
}
static void io_failure_recovery()
{
    Fixture f;
    f.ch = 8192;
    f.payload = std::string(16384, 'a');
    f.start();
    require(CloseHandle(part_handle(f.dir / "sx_in.part")) != 0, "could not invalidate fixture handle");
    bool threw = false;
    try { f.feed(f.chunk(0)); } catch (const std::exception&) { threw = true; }
    require(threw && f.sx->stats.recv == 0, "failed I/O counted as received");
    f.sx->tick(102, f.send);
    f.info();
    f.all();
    f.complete();
}
static void crc_retry()
{
    Fixture f;
    f.start();
    auto bad = f.chunk(0);
    bad.back() ^= 1;
    f.feed(bad);
    f.feed(f.chunk(1));
    f.feed(f.chunk(2));
    require(f.sx->stats.crcbad == 1 && f.sx->stats.done == 0, "bad CRC was published");
    f.all();
    f.complete();
}
static void crc_length_retry()
{
    Fixture f;
    Handle destination;
    f.start();
    put(f.dir / "sx_in.pkg", "previous package");
    destination.h = CreateFileW((f.dir / "sx_in.pkg").c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    require(destination.h != INVALID_HANDLE_VALUE, "could not block publication for corruption fixture");
    bool threw = false;
    try { f.all(); } catch (const std::exception&) { threw = true; }
    require(threw && f.sx->stats.done == 0, "publication was not blocked");
    // Publication failure closes the CRT stream. Modify only this closed file;
    // MSVC fopen_s intentionally denies other writers during active reception.
    {
        std::ofstream append(f.dir / "sx_in.part", std::ios::binary | std::ios::app);
        append << "extra bytes";
        append.close();
        require(!append.fail(), "could not extend fixture part file");
    }
    destination.close();
    f.sx->tick(102, f.send);
    require(f.sx->stats.crcbad == 1 && f.sx->stats.done == 0, "wrong file length was published");
    f.all();
    f.complete();
}
static void range_overflow()
{
    V obj = V::Object(), ranges = V::Arr(), pair = V::Arr();
    pair.a.push_back(V::Int(0));
    pair.a.push_back(V::Int(std::numeric_limits<int64_t>::max()));
    ranges.a.push_back(pair);
    obj.set("r", ranges);
    s2r::proto::SxStats stats;
    std::vector<std::string> sent;
    SaveXfer::serve("42", "abc", s2r::z::crc32("abc"), obj,
        [&](const std::string& data) { sent.push_back(data); }, stats);
    require(stats.sent == 1 && sent.size() == 2, "maximum range endpoint overflowed");
}
static void cancel_and_new_request()
{
    Fixture f;
    f.start();
    f.feed(f.chunk(0));
    auto old = f.chunk(1);
    fs::remove(f.dir / "sx_want.txt");
    f.sx->tick(101, f.send);
    f.feed(old);
    require(f.sx->stats.recv == 1 && f.sx->stats.done == 0, "cancelled request accepted a chunk");
    f.id = 43;
    put(f.dir / "sx_want.txt", "43");
    f.sx->tick(102, f.send);
    f.info();
    f.feed(old);
    f.all();
    f.complete();
}
static void peer_absent()
{
    Fixture f;
    put(f.dir / "sx_want.txt", "42");
    f.sx = std::make_unique<SaveXfer>(f.dir.wstring(), f.say);
    for (int i = 0; i < 1000; ++i) f.sx->tick(100 + i * 0.01, f.send);
    require(f.sent.size() <= 21 && f.sx->stats.done == 0, "absent peer caused request spam or completion");
    require(!fs::exists(f.dir / "sx_in.part"), "absent peer created partial save");
}
static void independent_receivers()
{
    Fixture a, b;
    b.id = 43;
    b.payload = "0123456789";
    a.start();
    b.start();
    a.feed(b.chunk(0));
    b.feed(a.chunk(0));
    require(a.sx->stats.recv == 0 && b.sx->stats.recv == 0, "receiver accepted another request's data");
    for (uint32_t i = 0; i < a.n(); ++i)
    {
        a.feed(a.chunk(i));
        b.feed(b.chunk(i));
    }
    a.complete();
    b.complete();
}

int main()
{
    struct Case { const char* name; void (*run)(); };
    const Case cases[] = {
        {"reorder_duplicate", reorder_duplicate}, {"lengths", lengths}, {"headers", headers},
        {"rename_retry", rename_retry}, {"resume_complete", resume_complete}, {"resume_partial", resume_partial},
        {"bad_bitmap", bad_bitmap}, {"empty_package", empty_package}, {"crc_reopen_failure", crc_reopen_failure},
        {"io_failure_recovery", io_failure_recovery}, {"crc_retry", crc_retry}, {"crc_length_retry", crc_length_retry}, {"range_overflow", range_overflow},
        {"cancel_and_new_request", cancel_and_new_request}, {"peer_absent", peer_absent},
        {"independent_receivers", independent_receivers},
    };
    int failures = 0;
    for (const auto& test : cases)
    {
        try { test.run(); std::printf("ok   %s\n", test.name); }
        catch (const std::exception& e) { ++failures; std::printf("FAIL %s: %s\n", test.name, e.what()); }
        std::fflush(stdout);
    }
    std::printf("%s (%d failed, %zu cases)\n", failures ? "FAIL" : "ALL PASS", failures, sizeof(cases) / sizeof(cases[0]));
    return failures ? 1 : 0;
}
