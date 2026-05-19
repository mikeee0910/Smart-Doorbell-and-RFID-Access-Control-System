/*
 * servo.h
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */

#ifndef INC_SERVO_H_
#define INC_SERVO_H_

#include "main.h"
#include <stdint.h>

/* Reed switch pin (rotation counting): ARD_D2 = PD14 */
#define LOCK_SW_GPIO_Port   GPIOD
#define LOCK_SW_Pin         GPIO_PIN_14

/* Lock position reed switch: ARD_D3 = PB0 */
#define LOCK_POS_GPIO_Port  GPIOB
#define LOCK_POS_Pin        GPIO_PIN_0

void Servo_Init(void);
void Servo_Stop(void);
void Servo_UnlockSequence(void);
int  Servo_UnlockOnly(void);   /* 0=OK, -1=timeout */
int  Servo_LockOnly(void);     /* 0=OK, -1=timeout */
int  Servo_IsLocked(void);     /* 1=locked (magnet present), 0=not locked */

#endif /* INC_SERVO_H_ */
