// Shared V2 firmware. sync_firmware.py copies this header into each Arduino sketch.
#pragma once
#include <AccelStepper.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

const uint8_t PIN_STEP=9, PIN_DIR=10, PIN_ENA=11, PIN_LIMIT=13;
AccelStepper stepper(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);
char cmdBuf[80];
uint8_t cmdLen=0;
bool discardLine=false, enabled=false;
uint8_t homePhase=0; // 0=idle, 1=release an already active sensor, 2=seek
int homeDir=-1;
float liveSpeed=DEFAULT_SPEED;
unsigned long lastCommand=0, homeStarted=0, sensorSince=0, lastEnc=0, lastState=0;
long commandId=0;
uint8_t sclPin=A4, sdaPin=A5;
bool pinsDetected=false;
const unsigned long WATCHDOG_MS=2000, HOME_TIMEOUT_MS=180000;

void enableDriver(bool on) { digitalWrite(PIN_ENA,on?LOW:HIGH); enabled=on; }
void haltMotion() {
  homePhase=0; sensorSince=0;
  stepper.setCurrentPosition(stepper.currentPosition()); // also clears target/speed
  enableDriver(false);
}
void sdaHigh(){pinMode(sdaPin,INPUT_PULLUP);}
void sdaLow(){digitalWrite(sdaPin,LOW);pinMode(sdaPin,OUTPUT);}
void sclHigh(){pinMode(sclPin,INPUT_PULLUP);}
void sclLow(){digitalWrite(sclPin,LOW);pinMode(sclPin,OUTPUT);}
void i2cDelay(){delayMicroseconds(3); if(enabled && !sensorSince) stepper.run();}
void i2cStart(){sdaHigh();sclHigh();i2cDelay();sdaLow();i2cDelay();sclLow();}
void i2cStop(){sdaLow();i2cDelay();sclHigh();i2cDelay();sdaHigh();i2cDelay();}
bool i2cWrite(uint8_t value){
  for(int i=7;i>=0;--i){if(value&(1<<i))sdaHigh();else sdaLow();i2cDelay();sclHigh();i2cDelay();sclLow();}
  sdaHigh();i2cDelay();sclHigh();i2cDelay();bool ack=digitalRead(sdaPin)==LOW;sclLow();return ack;
}
uint8_t i2cRead(bool ack){
  uint8_t value=0;sdaHigh();
  for(int i=7;i>=0;--i){sclHigh();i2cDelay();if(digitalRead(sdaPin))value|=(1<<i);sclLow();i2cDelay();}
  if(ack)sdaLow();else sdaHigh();i2cDelay();sclHigh();i2cDelay();sclLow();sdaHigh();return value;
}
int readRegister(uint8_t reg, bool twoBytes){
  i2cStart();
  if(!i2cWrite(0x36<<1)||!i2cWrite(reg)){i2cStop();return -1;}
  i2cStart();if(!i2cWrite((0x36<<1)|1)){i2cStop();return -1;}
  uint8_t hi=i2cRead(twoBytes),lo=twoBytes?i2cRead(false):0;i2cStop();
  return twoBytes?(((hi&15)<<8)|lo):hi;
}
int readEncoder(){
  int raw=readRegister(0x0E,true);
  if(raw>=0){pinsDetected=true;return raw;}
  pinsDetected=false;
  uint8_t tmp=sclPin;sclPin=sdaPin;sdaPin=tmp;
  raw=readRegister(0x0E,true);pinsDetected=raw>=0;return raw;
}
int magnetStatus(){
  int s=readRegister(0x0B,false);
  if(s<0||!(s&32))return 0;
  return s&8?2:(s&16?1:3);
}
void reportState(){
  Serial.print(F("STATE,"));Serial.print(stepper.currentPosition());Serial.print(',');
  Serial.print(stepper.targetPosition());Serial.print(',');Serial.print(commandId);Serial.print(',');
  Serial.println(homePhase||stepper.distanceToGo()!=0?1:0);
}
void failHome(const __FlashStringHelper* reason){haltMotion();Serial.print(F("HOME_FAILED,"));Serial.println(reason);}
void finishHome(){
  int raw=readEncoder();
  if(raw<0||magnetStatus()==0){failHome(F("encoder"));return;}
  haltMotion();stepper.setCurrentPosition(0);
  Serial.print(F("HOME_DONE,"));Serial.print(raw);Serial.println(F(",0,3"));
}
bool parseLong(const char* text,long &value){
  if(!text||!*text)return false;char* end;value=strtol(text,&end,10);return *end=='\0';
}
void processCmd(char* command){
  char* ctx=nullptr;char* op=strtok_r(command,",",&ctx);
  if(!op)return;
  if(!strcmp(op,"ID")){Serial.println(F(AXIS_NAME " READY V2"));return;}
  if(!strcmp(op,"PING")){lastCommand=millis();return;}
  if(!strcmp(op,"STOP")){lastCommand=millis();haltMotion();return;}
  long value=0,id=0;
  char* arg=strtok_r(nullptr,",",&ctx);
  if(!parseLong(arg,value)){Serial.println(F("ERROR,argument"));return;}
  if(!strcmp(op,"GOTO")){
    char* idArg=strtok_r(nullptr,",",&ctx);
    if(homePhase||value<MIN_TARGET||value>MAX_TARGET||!parseLong(idArg,id)||id<1){Serial.println(F("ERROR,target"));return;}
    commandId=id;lastCommand=millis();enableDriver(true);stepper.moveTo(value);
  }else if(!strcmp(op,"SPEED")){
    if(value<120||value>3000){Serial.println(F("ERROR,speed"));return;}
    liveSpeed=value;stepper.setMaxSpeed(liveSpeed);lastCommand=millis();
  }else if(!strcmp(op,"ACCEL")){
    if(value<1||value>10000){Serial.println(F("ERROR,accel"));return;}
    stepper.setAcceleration(value);lastCommand=millis();
  }else if(!strcmp(op,"HOME_SEARCH")){
    long speed=0;char* sp=strtok_r(nullptr,",",&ctx);
    if(!parseLong(sp,speed)||speed<120||speed>3000||(value!=-1&&value!=1)){Serial.println(F("ERROR,home"));return;}
    haltMotion();homeDir=value;liveSpeed=speed;stepper.setMaxSpeed(liveSpeed);
    homeStarted=lastCommand=millis();enableDriver(true);
    homePhase=digitalRead(PIN_LIMIT)==LOW?1:2;
    stepper.moveTo(stepper.currentPosition()+(homePhase==1?-homeDir*3000L:homeDir*120000L));
  }else Serial.println(F("ERROR,command"));
}
void setup(){
  Serial.begin(115200);pinMode(PIN_ENA,OUTPUT);pinMode(PIN_LIMIT,INPUT_PULLUP);
  enableDriver(false);sdaHigh();sclHigh();stepper.setMaxSpeed(liveSpeed);
  stepper.setAcceleration(DEFAULT_ACCEL);stepper.setMinPulseWidth(5);stepper.setCurrentPosition(0);
  lastCommand=millis();Serial.println(F(AXIS_NAME " READY V2"));
}
void loop(){
  unsigned long now=millis();
  if(enabled && now-lastCommand>WATCHDOG_MS){haltMotion();Serial.println(F("WATCHDOG"));}
  // Limit command processing per pass so a serial flood cannot starve stepping.
  for(uint8_t n=0;n<64 && Serial.available();++n){
    char c=Serial.read();
    if(c=='\n'){
      if(!discardLine){cmdBuf[cmdLen]='\0';processCmd(cmdBuf);}
      cmdLen=0;discardLine=false;
    }else if(c!='\r'&&!discardLine){
      if(cmdLen<sizeof(cmdBuf)-1)cmdBuf[cmdLen++]=c;
      else {cmdLen=0;discardLine=true;haltMotion();Serial.println(F("ERROR,line_length"));}
    }
  }
  now=millis();
  if(homePhase){
    if(now-homeStarted>HOME_TIMEOUT_MS){failHome(F("timeout"));}
    else if(homePhase==1 && digitalRead(PIN_LIMIT)==HIGH){
      homePhase=2;stepper.setCurrentPosition(stepper.currentPosition());
      stepper.moveTo(stepper.currentPosition()+homeDir*120000L);
    }else if(homePhase==2 && digitalRead(PIN_LIMIT)==LOW){
      if(!sensorSince)sensorSince=now?now:1;
      if(now-sensorSince>=10)finishHome();
    }else{
      sensorSince=0;
      if(stepper.distanceToGo()==0)failHome(F("travel_limit"));
    }
  }
  if(enabled&&!sensorSince)stepper.run();
  if(now-lastEnc>=100 && Serial.availableForWrite()>=40){
    lastEnc=now;int raw=readEncoder();int magnet=raw<0?0:magnetStatus();
    Serial.print(F("ENC,"));Serial.print(magnet?raw:-1);Serial.print(',');
    Serial.print(digitalRead(PIN_LIMIT));Serial.print(',');Serial.println(magnet);
  }
  if(now-lastState>=100 && Serial.availableForWrite()>=60){lastState=now;reportState();}
}
