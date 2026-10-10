/*
 * Main executable of Vibe RTTS.app.
 *
 * Started by the login agent (VIBE_RTTS_AGENT=1) it runs the app as a CHILD and
 * stays alive as its parent. That is the whole point: macOS attributes the
 * Microphone permission to the responsible process, and a parent living inside
 * the bundle makes that "Vibe RTTS" — with its usage string, so macOS can ask.
 * Exec'ing straight into python instead left a bare interpreter as the owner,
 * and the microphone came back starved (a fraction of a second per recording).
 *
 * Opened by a click, it runs the bundle's click script (start the agent, or tell
 * the running app to say where it is).
 *
 * VIBE_RTTS_REPO is baked in at build time by scripts/make-macos-app.sh.
 */
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include <mach-o/dyld.h>
#include <libgen.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    const char *agent = getenv("VIBE_RTTS_AGENT");
    if (!agent || strcmp(agent, "1") != 0) {
        char exe[4096];
        uint32_t size = sizeof(exe);
        if (_NSGetExecutablePath(exe, &size) != 0) return 1;
        char script[4200];
        snprintf(script, sizeof(script), "%s/../Resources/click.sh", dirname(exe));
        execl("/bin/bash", "bash", script, (char *)NULL);
        perror("vibe-rtts: exec click.sh");
        return 1;
    }

    char *argv[] = {"bash", VIBE_RTTS_REPO "/scripts/vibe-rtts.sh", NULL};
    if (posix_spawn(&child, "/bin/bash", NULL, NULL, argv, environ) != 0) {
        perror("vibe-rtts: spawn");
        return 1;
    }
    signal(SIGTERM, forward);   /* launchctl bootout / logout */
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        /* interrupted by a forwarded signal: keep waiting for the app to exit */
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
