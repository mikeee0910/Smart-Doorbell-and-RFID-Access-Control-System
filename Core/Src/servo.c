/*
 * servo.c
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */
#include "servo.h"
#include "cmsis_os.h"

extern TIM_HandleTypeDef htim2;

#define SERVO_TIMER      htim2
#define SERVO_CHANNEL    TIM_CHANNEL_1

#define SERVO_STOP_US    1500
#define SERVO_UNLOCK_US  1700
#define SERVO_LOCK_US    1300

#define UNLOCK_TIME_MS   600
#define HOLD_TIME_MS     3000
#define LOCK_TIME_MS     600

static void Servo_SetPulse(uint16_t pulse_us)
{
    __HAL_TIM_SET_COMPARE(&SERVO_TIMER, SERVO_CHANNEL, pulse_us);
}

void Servo_Init(void)
{
    HAL_TIM_PWM_Start(&SERVO_TIMER, SERVO_CHANNEL);
    Servo_Stop();
}

void Servo_Stop(void)
{
    Servo_SetPulse(SERVO_STOP_US);
}

void Servo_UnlockSequence(void)
{
    Servo_SetPulse(SERVO_UNLOCK_US);
    osDelay(UNLOCK_TIME_MS);

    Servo_Stop();
    osDelay(HOLD_TIME_MS);

    Servo_SetPulse(SERVO_LOCK_US);
    osDelay(LOCK_TIME_MS);

    Servo_Stop();
}

void Servo_UnlockOnly(void)
{
    Servo_SetPulse(SERVO_UNLOCK_US);
    osDelay(UNLOCK_TIME_MS);
    Servo_Stop();
}

void Servo_LockOnly(void)
{
    Servo_SetPulse(SERVO_LOCK_US);
    osDelay(LOCK_TIME_MS);
    Servo_Stop();
}

