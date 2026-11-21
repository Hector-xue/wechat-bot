// 在微信进程内存里暴力找 SQLCipher 密钥
// 判据：用候选 key 解密数据库第 1 页第 1 个块，结果应等于 "SQLite format 3\0" XOR salt
// 编译: gcc -O2 -o memscan memscan.c -lcrypto -lpthread
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <openssl/aes.h>
#include <openssl/hmac.h>
#include <openssl/evp.h>

static unsigned char page1_g[4096];

static int hmac_ok(const unsigned char *key) {
    unsigned char mac_salt[16], mac_key[32], digest[EVP_MAX_MD_SIZE];
    unsigned int dlen = 0;
    for (int i = 0; i < 16; i++) mac_salt[i] = page1_g[i] ^ 0x3A;
    if (!PKCS5_PBKDF2_HMAC((const char *)key, 32, mac_salt, 16, 2, EVP_sha512(), 32, mac_key))
        return 0;
    HMAC_CTX *ctx = HMAC_CTX_new();
    if (!ctx) return 0;
    unsigned int pageno = 1; unsigned char pn[4];
    for (int i = 0; i < 4; i++) pn[i] = (unsigned char)((pageno >> (8 * i)) & 0xFF);
    HMAC_Init_ex(ctx, mac_key, 32, EVP_sha512(), NULL);
    HMAC_Update(ctx, page1_g + 16, 4032 - 16);
    HMAC_Update(ctx, pn, 4);
    HMAC_Final(ctx, digest, &dlen);
    HMAC_CTX_free(ctx);
    return dlen == 64 && memcmp(digest, page1_g + 4096 - 64, 64) == 0;
}

static unsigned char salt[16], c1[16], target[16];
static int reserves[3] = {80, 64, 48};
static char *mem_path;
static volatile int found = 0;
static unsigned long long tested_total = 0;
static pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;

typedef struct { uint64_t start, end; } Region;
static Region regions[8192];
static int nregions = 0;

// 每个线程从 regions 里取任务
static int next_idx = 0;

static void *worker(void *arg) {
    (void)arg;
    unsigned long long tested = 0;
    const size_t CHUNK = 2 * 1024 * 1024;
    const size_t OVERLAP = 31;
    unsigned char *buf = malloc(CHUNK + 64);
    unsigned char out[16];
    AES_KEY aes;
    if (!buf) return NULL;

    int fd = open(mem_path, O_RDONLY);
    if (fd < 0) return NULL;

    for (;;) {
        pthread_mutex_lock(&mtx);
        int i = next_idx++;
        pthread_mutex_unlock(&mtx);
        if (i >= nregions || found) break;

        uint64_t pos = regions[i].start, end = regions[i].end;
        while (pos < end && !found) {
            size_t want = (end - pos > CHUNK) ? CHUNK : (size_t)(end - pos);
            ssize_t got = pread(fd, buf, want, (off_t)pos);
            if (got <= 0) { pos += want; continue; }   /* 跳过未落盘的页，别整块放弃 */
            size_t n = (size_t)got;
            for (size_t off = 0; off + 32 <= n; off += 8) {
                // 快筛：key 全 0 / 全 FF 不可能
                if (*(uint64_t *)(buf + off) == 0 && *(uint64_t *)(buf + off + 8) == 0) continue;
                AES_set_decrypt_key(buf + off, 256, &aes);
                AES_decrypt(c1, out, &aes);
                tested++;
                int hit = 0;
                for (int vi = 0; vi < 16 && !hit; vi++) {
                    const unsigned char *iv = page1_g + 4096 - 16 * (vi + 1);
                    unsigned char want[4] = {0x10 ^ iv[0], 0x00 ^ iv[1],
                                             0x01 ^ iv[2], 0x01 ^ iv[3]};
                    if (memcmp(out, want, 4) == 0) hit = 1;
                }
                /* 也试 IV = 文件盐（前 16 字节） */
                if (!hit) {
                    unsigned char want[4] = {0x10 ^ page1_g[0], 0x00 ^ page1_g[1],
                                             0x01 ^ page1_g[2], 0x01 ^ page1_g[3]};
                    if (memcmp(out, want, 4) == 0) hit = 1;
                }
                if (hit && hmac_ok(buf + off)) {
                    pthread_mutex_lock(&mtx);
                    if (!found) {
                        found = 1;
                        printf("FOUND_KEY=");
                        for (int k = 0; k < 32; k++) printf("%02x", buf[off + k]);
                        printf("\nADDR=0x%llx\n", (unsigned long long)(pos + off));
                        fflush(stdout);
                    }
                    pthread_mutex_unlock(&mtx);
                    break;
                }
            }
            pos += n - (n > OVERLAP ? OVERLAP : 0);
        }
    }
    close(fd);
    free(buf);
    pthread_mutex_lock(&mtx);
    tested_total += tested;
    pthread_mutex_unlock(&mtx);
    return NULL;
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <pid> <dbfile>\n", argv[0]); return 2; }
    int pid = atoi(argv[1]);

    FILE *f = fopen(argv[2], "rb");
    if (!f) { perror("db"); return 2; }
    unsigned char page[4096];
    if (fread(page, 1, sizeof(page), f) != sizeof(page)) { fprintf(stderr, "db too small\n"); return 2; }
    fclose(f);
    /* SQLCipher4: 文件前 16B 是 salt；加密区从偏移 16 开始；
       第一页 IV 在页尾保留区 4016..4032；明文前 6 字节固定为
       页大小 0x1000, 写版本 1, 读版本 1, 保留区 0x5040 */
    memcpy(page1_g, page, sizeof(page1_g));
    memcpy(c1, page + 16, 16);

    char maps[64];
    snprintf(maps, sizeof(maps), "/proc/%d/maps", pid);
    FILE *m = fopen(maps, "r");
    if (!m) { perror("maps"); return 2; }
    char line[512];
    while (fgets(line, sizeof(line), m)) {
        uint64_t a, b; char perm[8], rest[256];
        rest[0] = 0;
        if (sscanf(line, "%llx-%llx %7s %*s %*s %*s %255[^\n]", (unsigned long long *)&a, (unsigned long long *)&b, perm, rest) < 3) continue;
        if (perm[0] != 'r') continue;
        if (strstr(rest, "/dev/") || strstr(rest, "[vvar]") || strstr(rest, "[vsyscall]")) continue;
        if (rest[0] == '/' ) continue;                       /* 跳过文件映射（二进制/库） */
        if (perm[0] != 'r' || (perm[1] != 'w')) continue;    /* 只要可写区 */
        if (b - a < 64) continue;
        if (nregions < 8192) { regions[nregions].start = a; regions[nregions].end = b; nregions++; }
    }
    fclose(m);

    (void)salt; (void)target;
    mem_path = malloc(64);
    snprintf(mem_path, 64, "/proc/%d/mem", pid);

    printf("扫描 %d 个内存区段，线程 2\n", nregions);
    fflush(stdout);
    pthread_t t[2];
    for (int i = 0; i < 2; i++) pthread_create(&t[i], NULL, worker, NULL);
    for (int i = 0; i < 2; i++) pthread_join(t[i], NULL);

    if (!found) printf("NOT_FOUND tested=%llu\n", tested_total);
    return 0;
}
