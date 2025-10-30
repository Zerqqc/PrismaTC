#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <process.h>
#include <math.h>

#define MAX_KEYS 9
#define MAX_OBJECTS_PER_COLUMN 9999
#define PI 3.14159265358979323846

struct HitObject {
    int x, y, timestamp, object_type, end_time;
};

volatile BOOL stopClicking = FALSE;
volatile int timingShift = 0;
volatile int offset = 30;

typedef struct {
    WORD key;
    int press_time;
    int release_time;
    BOOL is_pressed;
} KeyState;

KeyState keyStates[MAX_KEYS];

struct ThreadData {
    struct HitObject* objects;
    int count;
    int columnIndex;
    int startTimeAdjustment;
    BOOL enableClicking;
    int offset;
};

void pressKey(WORD key) {
    INPUT input = {0};
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = key;
    SendInput(1, &input, sizeof(INPUT));
}

void releaseKey(WORD key) {
    INPUT input = {0};
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = key;
    input.ki.dwFlags = KEYEVENTF_KEYUP;
    SendInput(1, &input, sizeof(INPUT));
}

int compare_ints(const void* a, const void* b) {
    return (*(int*)a - *(int*)b);
}

void setupKeyBindings(int* columns, int columnCount, WORD* customKeys) {
    char keys[] = {'A', 'S', 'D', 'F', VK_SPACE, 'J', 'K', 'L', VK_OEM_1};
    int middleIndex = columnCount / 2;
    
    if (customKeys != NULL) {
        for (int i = 0; i < columnCount; i++) {
            keyStates[i].key = customKeys[i];
        }
        return;
    }
    if (columnCount % 2 == 1) {

        keyStates[middleIndex].key = VK_SPACE;
        for (int i = middleIndex - 1, keyIndex = 3; i >= 0; i--, keyIndex--) {
            keyStates[i].key = keys[keyIndex];
        }
        for (int i = middleIndex + 1, keyIndex = 5; i < columnCount; i++, keyIndex++) {
            keyStates[i].key = keys[keyIndex];
        }
    } else {

        for (int i = middleIndex - 1, keyIndex = 3; i >= 0; i--, keyIndex--) {
            keyStates[i].key = keys[keyIndex];
        }
        for (int i = middleIndex, keyIndex = 5; i < columnCount; i++, keyIndex++) {
            keyStates[i].key = keys[keyIndex];
        }
    }
}

int getKeyIndex(int x, int* columns, int columnCount) {
    for (int i = 0; i < columnCount; i++) {
        if (x == columns[i]) return i;
    }
    return -1;
}

int generateBellCurveOffset(int maxOffset) {
    double u1 = (double)rand() / RAND_MAX;
    double u2 = (double)rand() / RAND_MAX;
    double z = sqrt(-2.0 * log(u1)) * cos(2.0 * PI * u2);
    return (int)(z * maxOffset / 3.0 );
}

unsigned __stdcall columnPlayer(void* arg) {
    struct ThreadData* data = (struct ThreadData*)arg;
    LARGE_INTEGER frequency, startTime, currentTime;
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&startTime);

    KeyState* keyState = &keyStates[data->columnIndex];

    for (int i = 0; i < data->count; i++) {
        if (stopClicking) return 0;

        struct HitObject* obj = &data->objects[i];
        struct HitObject* nextObj = (i < data->count - 1) ? &data->objects[i + 1] : NULL;

        QueryPerformanceCounter(&currentTime);
        double elapsedTime = (double)(currentTime.QuadPart - startTime.QuadPart) * 1000.0 / frequency.QuadPart;

        int pressOffset = generateBellCurveOffset(offset);
        int releaseOffset = generateBellCurveOffset(offset);
       
        int pressTime = obj->timestamp - data->startTimeAdjustment + pressOffset + timingShift;
        int releaseTime = (obj->object_type == 128) ? obj->end_time - data->startTimeAdjustment + releaseOffset + timingShift : pressTime + 50 + releaseOffset;

        if (nextObj && releaseTime > nextObj->timestamp - data->startTimeAdjustment - 5) {
            releaseTime = nextObj->timestamp - data->startTimeAdjustment - 5;
        }

        while (elapsedTime < pressTime) {
            if (stopClicking) return 0;
            QueryPerformanceCounter(&currentTime);
            elapsedTime = (double)(currentTime.QuadPart - startTime.QuadPart) * 1000.0 / frequency.QuadPart;
        }

        if (data->enableClicking) {
            pressKey(keyState->key);
            keyState->is_pressed = TRUE;
        }

        while (elapsedTime < releaseTime) {
            if (stopClicking) return 0;
            QueryPerformanceCounter(&currentTime);
            elapsedTime = (double)(currentTime.QuadPart - startTime.QuadPart) * 1000.0 / frequency.QuadPart;
        }

        if (data->enableClicking) {
            releaseKey(keyState->key);
            keyState->is_pressed = FALSE;
        }
    }

    return 0;
}

void releaseAllKeys() {
    for (int i = 0; i < MAX_KEYS; i++) {
        if (keyStates[i].is_pressed) {
            releaseKey(keyStates[i].key);
            keyStates[i].is_pressed = FALSE;
        }
    }
}

__declspec(dllexport) void setStopClicking(BOOL value) {
    stopClicking = value;
    releaseAllKeys();
}

__declspec(dllexport) BOOL StopProgram() {
    return stopClicking;
}

__declspec(dllexport) void setTimingShift(int value) {
    timingShift = value;
}

__declspec(dllexport) void setOffset(int value) {
    offset = value;
}

__declspec(dllexport) void clickHitObjects(struct HitObject* hitObjects, int count, int unused1, int unused2, int startTimeAdjustment, BOOL enableClicking, int offset, int expectedColumnCount, WORD* customKeys) {
    srand((unsigned int)time(NULL));

    int columns[MAX_KEYS];
    int columnCount = 0;

    if (expectedColumnCount > 0 && expectedColumnCount <= MAX_KEYS) {
        double columnWidth = 512.0 / expectedColumnCount;
        for (int i = 0; i < expectedColumnCount; i++) {
            columns[i] = (int)((i + 0.5) * columnWidth);
        }
        columnCount = expectedColumnCount;
    } else {
        for (int i = 0; i < count; i++) {
            int x = hitObjects[i].x;
            int found = 0;
            for (int j = 0; j < columnCount; j++) {
                if (columns[j] == x) {
                    found = 1;
                    break;
                }
            }
            if (!found && columnCount < MAX_KEYS) {
                columns[columnCount++] = x;
            }
        }
    }

    qsort(columns, columnCount, sizeof(int), compare_ints);

    printf("Detected mode: %dK\n", columnCount);


    setupKeyBindings(columns, columnCount, customKeys);

    struct HitObject columnObjects[MAX_KEYS][MAX_OBJECTS_PER_COLUMN];
    int columnCounts[MAX_KEYS] = {0};


    for (int i = 0; i < count; i++) {
        int columnIndex = getKeyIndex(hitObjects[i].x, columns, columnCount);
        if (columnIndex != -1 && columnCounts[columnIndex] < MAX_OBJECTS_PER_COLUMN) {
            columnObjects[columnIndex][columnCounts[columnIndex]] = hitObjects[i];
            columnCounts[columnIndex]++;
        }
    }

    HANDLE threads[MAX_KEYS];
    struct ThreadData threadData[MAX_KEYS];


    for (int i = 0; i < columnCount; i++) {
        threadData[i].objects = columnObjects[i];
        threadData[i].count = columnCounts[i];
        threadData[i].columnIndex = i;
        threadData[i].startTimeAdjustment = startTimeAdjustment;
        threadData[i].enableClicking = enableClicking;
        threadData[i].offset = offset;

        threads[i] = (HANDLE)_beginthreadex(NULL, 0, columnPlayer, &threadData[i], 0, NULL);
    }


    WaitForMultipleObjects(columnCount, threads, TRUE, INFINITE);


    for (int i = 0; i < columnCount; i++) {
        CloseHandle(threads[i]);
    }

    printf("All columns completed.\n");
}
