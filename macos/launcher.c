/* Запуск Python внутри бандла, чтобы macOS показала доступ к локальной сети. */

#include <Python.h>

#include <arpa/inet.h>
#include <libgen.h>
#include <limits.h>
#include <locale.h>
#include <mach-o/dyld.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static void project_root(char *out, size_t capacity) {
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) {
        strncpy(out, ".", capacity - 1);
        out[capacity - 1] = '\0';
        return;
    }
    char real[PATH_MAX];
    if (realpath(exe, real) == NULL) {
        strncpy(out, ".", capacity - 1);
        out[capacity - 1] = '\0';
        return;
    }
    /* .../Hyperion.app/Contents/MacOS/Hyperion → каталог проекта */
    for (int step = 0; step < 4; step++) {
        char *slash = strrchr(real, '/');
        if (slash == NULL) {
            break;
        }
        *slash = '\0';
    }
    strncpy(out, real, capacity - 1);
    out[capacity - 1] = '\0';
}

int main(int argc, char **argv) {
    char root[PATH_MAX];
    const char *home = getenv("HOME");
    char pyhome[PATH_MAX];
    setlocale(LC_ALL, "en_US.UTF-8");
    project_root(root, sizeof(root));
    if (chdir(root) != 0) {
        perror("chdir");
        return 1;
    }
    if (home == NULL) {
        home = "/Users/bulai-afk";
    }
    snprintf(pyhome, sizeof(pyhome), "%s/.pyenv/versions/3.11.9", home);
    setenv("PYTHONHOME", pyhome, 1);
    setenv("PYTHONPATH", root, 1);

    char *pyargv[] = {argv[0], "-m", "app.hyperion_app", NULL};
    (void)argc;
    return Py_BytesMain(3, pyargv);
}
