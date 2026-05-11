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

void Servo_Init(void);
void Servo_Stop(void);
void Servo_UnlockSequence(void);
void Servo_UnlockOnly(void);
void Servo_LockOnly(void);

#endif /* INC_SERVO_H_ */
