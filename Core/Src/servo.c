/*
 * servo.c
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */
#include "servo.h"
#include "cmsis_os.h"
#include <stdio.h>

extern TIM_HandleTypeDef htim2;

#define SERVO_TIMER      htim2
#define SERVO_CHANNEL    TIM_CHANNEL_1

#define SERVO_STOP_US    1500
#define SERVO_UNLOCK_US  1700
#define SERVO_LOCK_US    1300

#define NUM_TURNS        2       /* lock/unlock need 2 full turns */
#define SERVO_TIMEOUT_MS 5000    /* max time to wait */

static void Servo_SetPulse(uint16_t pulse_us)
{
    __HAL_TIM_SET_COMPARE(&SERVO_TIMER, SERVO_CHANNEL, pulse_us);
}

static int Servo_ReadSwitch(void)
{
    return (HAL_GPIO_ReadPin(LOCK_SW_GPIO_Port, LOCK_SW_Pin) == GPIO_PIN_SET) ? 1 : 0;
}

void Servo_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Rotation counting reed switch (PD14) */
    GPIO_InitStruct.Pin  = LOCK_SW_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLDOWN;
    HAL_GPIO_Init(LOCK_SW_GPIO_Port, &GPIO_InitStruct);

    /* Lock position reed switch (PB0) */
    GPIO_InitStruct.Pin  = LOCK_POS_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLDOWN;
    HAL_GPIO_Init(LOCK_POS_GPIO_Port, &GPIO_InitStruct);

    HAL_TIM_PWM_Start(&SERVO_TIMER, SERVO_CHANNEL);
    Servo_Stop();
}

void Servo_Stop(void)
{
    Servo_SetPulse(SERVO_STOP_US);
}

/*
 * Count reed switch transitions to detect full rotations.
 * Counts falling edges (HIGH -> LOW = magnet passed by).
 * Returns 0 on success, -1 on timeout.
 */
static int Servo_WaitTurns(int num_turns)
{
    int count = 0;
    int prev = Servo_ReadSwitch();
    uint32_t timeout = HAL_GetTick() + SERVO_TIMEOUT_MS;

    while (count < num_turns && HAL_GetTick() < timeout) {
        int curr = Servo_ReadSwitch();
        if (prev == 1 && curr == 0) {
            count++;
            printf("Servo: turn %d/%d\r\n", count, num_turns);
        }
        prev = curr;
        osDelay(5);
    }

    Servo_Stop();

    if (count < num_turns) {
        printf("Servo: TIMEOUT (%d/%d turns)\r\n", count, num_turns);
        return -1;
    }
    return 0;
}

void Servo_UnlockSequence(void)
{
    Servo_UnlockOnly();
    osDelay(3000);
    Servo_LockOnly();
}

int Servo_UnlockOnly(void)
{
    printf("Servo: unlocking...\r\n");
    Servo_SetPulse(SERVO_UNLOCK_US);
    return Servo_WaitTurns(NUM_TURNS);
}

int Servo_LockOnly(void)
{
    printf("Servo: locking...\r\n");
    Servo_SetPulse(SERVO_LOCK_US);
    return Servo_WaitTurns(NUM_TURNS);
}

int Servo_IsLocked(void)
{
    return (HAL_GPIO_ReadPin(LOCK_POS_GPIO_Port, LOCK_POS_Pin) == GPIO_PIN_SET) ? 1 : 0;
}
