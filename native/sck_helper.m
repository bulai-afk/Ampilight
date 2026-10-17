#import <errno.h>
#import <stdint.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>
#import <sys/mman.h>
#import <sys/stat.h>
#import <fcntl.h>
#import <unistd.h>
#import <stdatomic.h>
#import <pthread/qos.h>

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

int main(int argc, char **argv) {
  pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
  if (argc < 5) {
    fprintf(stderr, "ERR usage\n");
    return 2;
  }
  const char *path = argv[1];
  uint32_t displayID = (uint32_t)strtoul(argv[2], NULL, 10);
  int maxEdge = atoi(argv[3]);
  int fps = atoi(argv[4]);

  int fd = open(path, O_RDWR | O_CREAT, 0600);
  if (fd < 0) {
    fprintf(stderr, "ERR open\n");
    return 2;
  }
  if (ftruncate(fd, sizeof(FrameMap)) != 0) {
    fprintf(stderr, "ERR truncate\n");
    return 2;
  }
  FrameMap *map = mmap(NULL, sizeof(FrameMap), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (map == MAP_FAILED) {
    fprintf(stderr, "ERR mmap\n");
    return 2;
  }
  memset(map, 0, sizeof(uint32_t) * 4);

  char err[512] = {0};
  int rc = sck_start(displayID, maxEdge, fps, on_frame, map, err, (int)sizeof(err));
  if (rc != 0) {
    fprintf(stderr, "ERR %s\n", err[0] ? err : "start");
    return 1;
  }
  fprintf(stderr, "READY\n");
  fflush(stderr);

  char sink[64];
  while (read(STDIN_FILENO, sink, sizeof(sink)) > 0) {
  }
  sck_stop();
  return 0;
}
