/* Захват внутри процесса Hyperion, чтобы macOS спросила разрешение у этого приложения. */

#import <errno.h>
#import <stdint.h>
#import <stdio.h>
#import <string.h>
#import <sys/mman.h>
#import <sys/stat.h>
#import <fcntl.h>
#import <unistd.h>
#import <stdatomic.h>

typedef void (*SCKFrameCallback)(const uint8_t *bgra, int width, int height, int stride, void *ctx);
int sck_start(uint32_t displayID, int maxEdge, int fps, SCKFrameCallback callback, void *ctx,
              char *errbuf, int errlen);
void sck_stop(void);

enum { kMaxBytes = 1600 * 1600 * 4 };

typedef struct {
  _Atomic uint32_t seq;
  uint32_t width;
  uint32_t height;
  uint32_t stride;
  uint8_t pixels[kMaxBytes];
} FrameMap;

static FrameMap *gMap = NULL;
static int gFd = -1;

static void on_frame(const uint8_t *bgra, int width, int height, int stride, void *ctx) {
  FrameMap *map = ctx;
  size_t nbytes = (size_t)stride * (size_t)height;
  if (bgra == NULL || width <= 0 || height <= 0 || stride < width * 4 || nbytes > kMaxBytes) {
    return;
  }
  uint32_t seq = atomic_load_explicit(&map->seq, memory_order_relaxed);
  atomic_store_explicit(&map->seq, seq + 1, memory_order_release);
  memcpy(map->pixels, bgra, nbytes);
  map->width = (uint32_t)width;
  map->height = (uint32_t)height;
  map->stride = (uint32_t)stride;
  atomic_store_explicit(&map->seq, seq + 2, memory_order_release);
}

static void close_map(void) {
  if (gMap != NULL) {
    munmap(gMap, sizeof(FrameMap));
    gMap = NULL;
  }
  if (gFd >= 0) {
    close(gFd);
    gFd = -1;
  }
}

int sck_session_start(const char *path, uint32_t displayID, int maxEdge, int fps, char *errbuf,
                      int errlen) {
  sck_stop();
  close_map();
  if (errbuf && errlen > 0) {
    errbuf[0] = 0;
  }
  if (path == NULL || path[0] == 0) {
    return 2;
  }
  int fd = open(path, O_RDWR | O_CREAT, 0600);
  if (fd < 0) {
    return 2;
  }
  if (ftruncate(fd, sizeof(FrameMap)) != 0) {
    close(fd);
    return 2;
  }
  FrameMap *map = mmap(NULL, sizeof(FrameMap), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (map == MAP_FAILED) {
    close(fd);
    return 2;
  }
  memset(map, 0, sizeof(uint32_t) * 4);
  gFd = fd;
  gMap = map;
  int rc = sck_start(displayID, maxEdge, fps, on_frame, map, errbuf, errlen);
  if (rc != 0) {
    close_map();
  }
  return rc;
}

void sck_session_stop(void) {
  sck_stop();
  close_map();
}
